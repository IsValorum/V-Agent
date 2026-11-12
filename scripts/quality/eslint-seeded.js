// Deliberate faults: ESLint must report them before a clean result on the interface is trusted.
function seeded() { return undefinedVariable + 1; }
if (typeof seeded === 'fucntion') {}
if (seeded = 2) {}
