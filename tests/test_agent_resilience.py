"""A long agentic turn survives engine/provider hiccups and does not outgrow the model's window."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import agent_resilience as r  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def test_transient_provider_and_connection_errors_are_retried(self):
        for text in ('Error del proveedor (429): demasiadas peticiones.', 'Error del proveedor (503): el proveedor tuvo un error.',
                     'Error del motor (502): bad gateway', 'Error del proveedor (529): overloaded',
                     'La respuesta del proveedor se cortó antes de terminar (la conexión se cerró a mitad).'):
            self.assertEqual(r.classify(ValueError(text)), 'transient', text)
        self.assertEqual(r.classify(ConnectionResetError(10054, 'reset')), 'transient')
        self.assertEqual(r.classify(TimeoutError('timed out')), 'transient')

    def test_context_overflow_is_recognised_for_llama_and_providers(self):
        for text in ('Error del proveedor (400): el proveedor rechazó la petición. Detalle: the request exceeds the available context size, try increasing it',
                     "Error del proveedor (400): Detalle: This model's maximum context length is 131072 tokens",
                     'Error del proveedor (400): Detalle: prompt is too long: 210000 tokens > 200000 maximum',
                     'Error del proveedor (413): payload too large'):
            self.assertEqual(r.classify(ValueError(text)), 'overflow', text)

    def test_errors_that_retrying_cannot_fix_stop_the_turn(self):
        for text in ('Error del proveedor (401): la clave no es válida.', 'Error del proveedor (404): model not found',
                     'Error del proveedor (400): invalid tool schema', 'Selecciona un modelo de la API antes de chatear.'):
            self.assertIsNone(r.classify(ValueError(text)), text)

    def test_waits_grow(self):
        self.assertLess(r.delay(1), r.delay(2))
        self.assertLess(r.delay(2), r.delay(3))
        self.assertEqual(r.delay(9), r.delay(3))


def transcript(rounds, size=6000):
    messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'build the site'}]
    for i in range(rounds):
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'call_%d' % i, 'type': 'function',
             'function': {'name': 'pc__fs_write', 'arguments': json.dumps({'path': 'f%d.txt' % i, 'content': 'x' * size})}}]})
        messages.append({'role': 'tool', 'tool_call_id': 'call_%d' % i, 'content': 'y' * size})
    return messages


class FitTests(unittest.TestCase):
    def test_nothing_changes_while_well_inside_the_window(self):
        messages = transcript(2, 500)
        out, report = r.fit(messages, 32768)
        self.assertIs(out, messages)
        self.assertIsNone(report)

    def test_unknown_window_changes_nothing_unless_forced(self):
        messages = transcript(20)
        self.assertIsNone(r.fit(messages, 0)[1])
        out, report = r.fit(messages, 0, force=True)
        self.assertLess(r.chars(out), r.chars(messages))

    def test_a_long_turn_is_brought_back_under_the_window_keeping_its_shape(self):
        messages = transcript(20)
        window = 16384
        self.assertGreater(r.chars(messages), window * r.CHARS_PER_TOKEN)
        out, report = r.fit(messages, window)
        self.assertIsNotNone(report)
        self.assertLess(r.chars(out), window * r.CHARS_PER_TOKEN * 0.9)
        # Every call still has its result, the user's words and the rules are whole, the last step intact.
        self.assertEqual([m['role'] for m in out], [m['role'] for m in messages])
        self.assertEqual(out[:2], messages[:2])
        self.assertEqual(out[-2:], messages[-2:])
        for message in out:
            for call in message.get('tool_calls') or []:
                json.loads(call['function']['arguments'])
        self.assertIn('shortened', out[3]['content'])

    def test_archive_is_used_first_when_there_is_a_folder(self):
        seen = []

        def archive(messages, keep):
            seen.append(keep)
            return messages[:2] + [{'role': 'assistant', 'content': '[archived]'}] + messages[-keep * 2:], {'offloaded_batches': 7}

        out, report = r.fit(transcript(20), 16384, archive=archive)
        self.assertEqual(seen, [4])
        self.assertEqual(report['archived_batches'], 7)
        self.assertIn('[archived]', json.dumps(out))

    def test_input_is_never_modified(self):
        messages = transcript(20)
        copy = json.dumps(messages)
        r.fit(messages, 8192, force=True)
        self.assertEqual(json.dumps(messages), copy)


if __name__ == '__main__':
    unittest.main()
