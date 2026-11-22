"""Reasoning that an engine streams inside the reply text instead of its own field (Strata Rust).

Strata Rust sends a thinking model's whole output as `content`: the reasoning, `</think>`, then the reply. The
interface then showed the reasoning as the answer, and the next turn sent it back as the reply text, so the
history no longer matched what the engine had read. This splits the stream at the marks into
`reasoning_content` and `content`, as llama.cpp does with its reasoning parser."""
import json

START, END = '<think>', '</think>'


def opens_think(template):
    """The chat template starts the model's turn inside a think block (Qwen3.5/3.6 with thinking on)."""
    if not isinstance(template, str):
        return False
    at = template.rfind('add_generation_prompt')
    return at >= 0 and START in template[at:]


def _partial_end(text):
    """How many trailing characters could be the start of END split across chunks."""
    for n in range(min(len(END) - 1, len(text)), 0, -1):
        if END.startswith(text[-n:]):
            return n
    return 0


class ThinkSplit:
    def __init__(self, thinking):
        # 'reasoning' when the prompt already opened the think block; 'start' looks for a <think> the model writes.
        self.state = 'reasoning' if thinking else 'start'
        self.held = ''
        self.after_end = False

    def feed(self, text, final=False):
        """(reasoning, content) ready to pass on; text that may still be part of a mark is held back."""
        reasoning = content = ''
        self.held += text or ''
        while True:
            if self.state == 'start':
                rest = self.held.lstrip()
                if rest.startswith(START):
                    self.held, self.state = rest[len(START):], 'reasoning'
                    continue
                if START.startswith(rest) and not final:
                    break
                self.state = 'content'
                continue
            if self.state == 'reasoning':
                at = self.held.find(END)
                if at >= 0:
                    reasoning += self.held[:at]
                    self.held, self.state, self.after_end = self.held[at + len(END):], 'content', True
                    continue
                keep = 0 if final else _partial_end(self.held)
                reasoning += self.held[:len(self.held) - keep]
                self.held = self.held[len(self.held) - keep:]
                break
            if self.after_end:
                # The template writes "</think>\n\n" before the reply: those line breaks are not reply text.
                rest = self.held.lstrip('\n')
                if not rest and not final:
                    self.held = ''
                    break
                self.held, self.after_end = rest, False
            content += self.held
            self.held = ''
            break
        return reasoning, content

    def line(self, raw):
        """One `data: {...}` SSE line with its delta text split; other lines come back unchanged."""
        try:
            packet = json.loads(raw[6:])
        except ValueError:
            return raw
        changed = False
        for choice in packet.get('choices') or []:
            delta = choice.get('delta') if isinstance(choice, dict) else None
            if not isinstance(delta, dict):
                continue
            text, final = delta.get('content'), bool(choice.get('finish_reason'))
            if not isinstance(text, str) and not final:
                continue
            reasoning, content = self.feed(text if isinstance(text, str) else '', final)
            if reasoning:
                delta['reasoning_content'] = (delta.get('reasoning_content') or '') + reasoning
            if content:
                delta['content'] = content
            else:
                delta.pop('content', None)
            changed = True
        return ('data: ' + json.dumps(packet, ensure_ascii=False) + '\n').encode() if changed else raw
