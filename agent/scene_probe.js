/* Read-only scene telemetry. Uses the page's own Three.js module; no screenshots or model vision. */
(async () => {
  const probeStart=performance.now();
  let three=window.THREE;
  if(!three){
    let url;
    for(const script of document.querySelectorAll('script[type="importmap"]')){
      try{url=JSON.parse(script.textContent).imports?.three;if(url)break;}catch{}
    }
    if(!url)return {available:false,reason:'No supported scene runtime exposed by this page.'};
    try{three=await import(url);}catch(error){return {available:false,reason:'Scene module unavailable: '+error.message};}
  }
  if(!three.Object3D?.prototype)return {available:false,reason:'Unsupported scene API.'};
  let scene=null,camera=null;const cameras=new Set(),previousWorld=new Map();
  for(const {value} of Object.values(Object.getOwnPropertyDescriptors(window))){
    try{if(value?.isScene)scene=value;if(value?.isCamera)cameras.add(value);}catch{}
  }
  const original=three.Object3D.prototype.updateMatrixWorld;
  const capture=function(...args){
    if(this.isScene)scene=this;
    if(this.isCamera)cameras.add(this);
    if(this.isMesh&&!this.isInstancedMesh&&this.geometry?.type==='BoxGeometry'&&previousWorld.size<24)
      previousWorld.set(this,this.matrixWorld.clone());
    return original.apply(this,args);
  };
  three.Object3D.prototype.updateMatrixWorld=capture;
  try{
    const deadline=performance.now()+900;
    while((!scene||!cameras.size)&&performance.now()<deadline)await new Promise(resolve=>setTimeout(resolve,40));
  }finally{
    if(three.Object3D.prototype.updateMatrixWorld===capture)three.Object3D.prototype.updateMatrixWorld=original;
  }
  if(!scene)return {available:false,framework:'three',reason:'Scene not observed in a render frame. It may still be loading or static.'};
  const shadowCameras=new Set();scene.traverse(object=>{if(object.shadow?.camera)shadowCameras.add(object.shadow.camera);});
  const views=[...cameras].filter(view=>!shadowCameras.has(view));
  camera=views.find(view=>view.isPerspectiveCamera)||views[0]||null;
  const result={available:true,framework:'three',revision:String(three.REVISION),visual_verified:false,
    camera:camera?{type:camera.type,position:camera.position.toArray(),near:camera.near,far:camera.far,fov:camera.fov}:null,
    meshes:0,instanced_meshes:0,active_instances:0,empty_instance_groups:0,issues:[],examples:[]};
  const point=new three.Vector3(),matrix=new three.Matrix4();let projected=0,inFrame=0;
  scene.traverse(object=>{
    if(!object.isMesh)return;
    result.meshes++;
    const label=object.name||object.material?.name||object.material?.color?.getHexString?.()||object.uuid.slice(0,8);
    if(!object.matrixWorld.elements.every(Number.isFinite))result.issues.push({kind:'invalid_world_matrix',severity:'error',object:label});
    if(object.isInstancedMesh){
      result.instanced_meshes++;
      const count=object.count,capacity=object.instanceMatrix.count;
      result.active_instances+=Math.max(0,count);
      if(count===0)result.empty_instance_groups++;
      if(count>capacity||count<0)result.issues.push({kind:'instance_count_out_of_bounds',severity:'error',object:label,count,capacity});
      const invalid=[];
      const n=Math.max(0,Math.min(count,capacity));
      for(let sample=0;sample<Math.min(n,64);sample++){
        const index=n<=64?sample:Math.floor(sample*(n-1)/63);
        object.getMatrixAt(index,matrix);
        if(!matrix.elements.every(Number.isFinite)){invalid.push(index);continue;}
        if(camera&&object.visible){
          point.setFromMatrixPosition(matrix).applyMatrix4(object.matrixWorld).project(camera);projected++;
          if(Math.abs(point.x)<=1&&Math.abs(point.y)<=1&&Math.abs(point.z)<=1)inFrame++;
        }
      }
      if(invalid.length)result.issues.push({kind:'non_finite_instance_matrices',severity:'error',object:label,indices:invalid.slice(0,8)});
      if(result.examples.length<8)result.examples.push({object:label,instances:count,capacity});
    }
    if(object.visible&&object.material&&!Array.isArray(object.material)&&object.material.transparent&&object.material.opacity===0)
      result.issues.push({kind:'fully_transparent_mesh',severity:'warning',object:label});
  });
  if(result.instanced_meshes&&result.empty_instance_groups===result.instanced_meshes)
    result.issues.unshift({kind:'all_instance_groups_empty',severity:'warning',message:'Every InstancedMesh has count=0: none of its instances can be drawn. Check count initialization, insertion and finalization.'});
  else if(result.empty_instance_groups)result.issues.push({kind:'empty_instance_groups',severity:'info',count:result.empty_instance_groups});
  if(projected&&!inFrame)result.issues.push({kind:'sampled_centres_outside_camera',severity:'warning',samples:projected,message:'All sampled instance centres are outside the camera frustum. Check transforms and camera framing; large intersecting objects may still be visible.'});
  result.sampled_instance_centres={total:projected,in_camera:inFrame};
  // Compare moving parts with static instances. A numerical overlap is evidence
  // to inspect, not a judgement about design: axles and joints can intersect.
  const solid=object=>object.visible&&!Array.isArray(object.material)&&object.material&&
    !(object.material.transparent&&object.material.opacity<0.98);
  const movers=[],instanceVersions=new Map();
  scene.traverse(object=>{
    if(object.isInstancedMesh)instanceVersions.set(object,object.instanceMatrix.version);
    if(object.isMesh&&!object.isInstancedMesh&&solid(object)&&object.geometry?.type==='BoxGeometry'&&movers.length<24)
      movers.push({object,before:previousWorld.get(object)||object.matrixWorld.clone()});
  });
  if(movers.length&&!previousWorld.size){
    await new Promise(resolve=>{const timer=setTimeout(resolve,900);requestAnimationFrame(()=>{clearTimeout(timer);setTimeout(resolve,0);});});
    scene.updateMatrixWorld(true);
  }
  function bounds(object,world){
    if(!world.elements.every(Number.isFinite))return null;
    const geometry=object.geometry;if(!geometry.boundingBox)geometry.computeBoundingBox();
    const box=geometry.boundingBox;if(!box||box.isEmpty())return null;
    const axes=[0,1,2].map(index=>new three.Vector3().setFromMatrixColumn(world,index));
    const scale=axes.map(axis=>axis.length());if(scale.some(value=>value<1e-8))return null;
    axes.forEach((axis,index)=>axis.multiplyScalar(1/scale[index]));
    // OBB SAT assumes orthogonal axes; do not misreport sheared transforms.
    if(Math.abs(axes[0].dot(axes[1]))+Math.abs(axes[0].dot(axes[2]))+Math.abs(axes[1].dot(axes[2]))>1e-5)return null;
    return {centre:box.getCenter(new three.Vector3()).applyMatrix4(world),axes,
      half:box.getSize(new three.Vector3()).multiplyScalar(.5).toArray().map((value,index)=>value*scale[index]),
      aabb:box.clone().applyMatrix4(world)};
  }
  function penetration(a,b){
    const delta=b.centre.clone().sub(a.centre),axes=[...a.axes,...b.axes];
    for(const x of a.axes)for(const y of b.axes){const axis=x.clone().cross(y);if(axis.lengthSq()>1e-10)axes.push(axis.normalize());}
    let depth=Infinity;
    for(const axis of axes){
      const radius=obb=>obb.axes.reduce((sum,basis,index)=>sum+obb.half[index]*Math.abs(basis.dot(axis)),0);
      const overlap=radius(a)+radius(b)-Math.abs(delta.dot(axis));
      if(overlap<=.025)return 0;depth=Math.min(depth,overlap);
    }
    return depth;
  }
  const moving=movers.filter(({object,before})=>object.matrixWorld.elements.some((value,index)=>Math.abs(value-before.elements[index])>1e-5))
    .map(({object})=>({object,box:bounds(object,object.matrixWorld)})).filter(item=>item.box);
  const spatial={scope:'Moving box meshes vs static instanced boxes, at an observed animation frame; not a full motion or visual audit.',
    moving_box_meshes:moving.length,static_instances_checked:0,tested_pairs:0,contacts:0,complete:true,bounds_only:true};
  const spatialStart=performance.now(),partContacts=new Map();
  if(moving.length)scene.traverse(object=>{
    if(!object.isInstancedMesh||instanceVersions.get(object)!==object.instanceMatrix.version||!solid(object)||object.geometry?.type!=='BoxGeometry'||!spatial.complete)return;
    const count=Math.max(0,Math.min(object.count,object.instanceMatrix.count));
    const local=new three.Matrix4(),world=new three.Matrix4();
    for(let index=0;index<count;index++){
      if(spatial.static_instances_checked>=40000||performance.now()-spatialStart>1200){spatial.complete=false;break;}
      object.getMatrixAt(index,local);world.multiplyMatrices(object.matrixWorld,local);
      const box=bounds(object,world);spatial.static_instances_checked++;if(!box)continue;
      for(const item of moving){
        if(!item.box.aabb.intersectsBox(box.aabb))continue;
        spatial.tested_pairs++;const depth=penetration(item.box,box);if(!depth)continue;
        spatial.contacts++;
        let part=partContacts.get(item.object.uuid);
        if(!part){
          part={moving:item.object.name||item.object.parent?.name||((item.object.material.color?.getHexString?.()||'box')+' ['+item.object.uuid.slice(0,4)+']'),
            position:item.box.centre.toArray().map(value=>Number(value.toFixed(2))),count:0,examples:[]};
          partContacts.set(item.object.uuid,part);
        }
        part.count++;
        if(part.examples.length<2)part.examples.push({static:object.name||object.material.color?.getHexString?.()||object.uuid.slice(0,8),instance:index,
          centre:box.centre.toArray().map(value=>Number(value.toFixed(2))),depth:Number(depth.toFixed(3))});
      }
    }
  });
  result.spatial_checks=spatial;
  const contacts=[...partContacts.values()].slice(0,12);
  if(contacts.length)result.issues.push({kind:'moving_part_intersections',severity:'warning',contacts,
    message:'Moving box parts penetrate static boxes. Inspect placement and rotation planes; joints can be intentional. No automatic edit was made.'});
  result.issues=result.issues.slice(0,12);
  result.timings_ms={total:Math.round(performance.now()-probeStart),spatial:Math.round(performance.now()-spatialStart)};
  return result;
})()
