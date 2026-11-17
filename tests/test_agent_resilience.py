"""A long agentic turn survives engine/provider hiccups and does not outgrow the model's window."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import agent_resilience as r  # noqa: E402


class ClassifyTests(unittest.TestCase):
    """Error classes as OpenCode / Goose define them (see agent_resilience's header)."""

    def test_throttles_overload_and_dropped_connections_are_retried(self):
        for text in ('Error del proveedor (429): se alcanzó el límite de uso o de velocidad del proveedor; espera un poco.',
                     'Error del proveedor (503): el proveedor está saturado o no disponible ahora mismo.',
                     'Error del motor (502): bad gateway', 'Error del proveedor (529): el proveedor está saturado ahora mismo. Detalle: Overloaded',
                     'La respuesta del proveedor se cortó antes de terminar (la conexión se cerró a mitad).',
                     'upstream connect error or disconnect/reset before headers'):
            self.assertEqual(r.classify(ValueError(text)), 'transient', text)
        self.assertEqual(r.classify(ConnectionResetError(10054, 'reset')), 'transient')

    def test_status_carried_by_the_error_decides_before_its_wording(self):
        import engine_manager
        busy = engine_manager.ProviderHTTPError('Error del proveedor (529): x.', 529, 4000)
        self.assertEqual(r.classify(busy), 'transient')
        rejected = engine_manager.ProviderHTTPError('Error del proveedor (400): please try again with valid json', 400)
        self.assertIsNone(r.classify(rejected))

    def test_context_overflow_is_recognised_for_llama_and_providers(self):
        for text in ('Error del proveedor (400): Detalle: the request exceeds the available context size, try increasing it',
                     "Error del proveedor (400): Detalle: This model's maximum context length is 131072 tokens",
                     'Error del proveedor (400): Detalle: prompt is too long: 210000 tokens > 200000 maximum',
                     'Error del proveedor (413): payload too large'):
            self.assertEqual(r.classify(ValueError(text)), 'overflow', text)
        # A 429 worded like an overflow is a throttle (Bedrock's "Too many tokens, please wait").
        self.assertEqual(r.classify(ValueError('Error del proveedor (429): Too many tokens, please wait')), 'transient')

    def test_quota_and_rejections_stop_the_turn(self):
        for text in ('Error del proveedor (402): no queda saldo o crédito en la cuenta del proveedor. Detalle: Insufficient Balance',
                     'Error del proveedor (429): Detalle: You exceeded your current quota, insufficient_quota',
                     'Error del proveedor (401): la clave no es válida.', 'Error del proveedor (404): model not found',
                     'Error del proveedor (400): invalid tool schema', 'Selecciona un modelo de la API antes de chatear.'):
            self.assertIsNone(r.classify(ValueError(text)), text)

    def test_no_network_path_retries_for_an_hour_and_timeouts_three_times(self):
        import socket
        self.assertEqual(r.classify(socket.gaierror(11001, 'getaddrinfo failed')), 'unreachable')
        self.assertTrue(r.allowed('unreachable', 500, 3599))
        self.assertFalse(r.allowed('unreachable', 2, 3601))
        self.assertEqual(r.classify(TimeoutError('timed out')), 'timeout')
        self.assertTrue(r.allowed('timeout', 3, 0))
        self.assertFalse(r.allowed('timeout', 4, 0))

    def test_schedule_grows_with_jitter_and_honours_retry_after(self):
        plain = [r.delay(i, jitter=False) for i in range(1, 11)]
        self.assertEqual(plain[:5], [2.0, 4.0, 8.0, 16.0, 30.0])
        self.assertEqual(max(plain), 30.0)
        self.assertTrue(180 <= sum(plain) <= 260, sum(plain))  # about 3.5 minutes for a provider that stays busy
        for _ in range(50):
            self.assertTrue(1.6 <= r.delay(1) <= 2.4)
        self.assertEqual(r.delay(1, retry_after_ms=45000), 45.0)
        self.assertEqual(r.delay(1, retry_after_ms=10 ** 9), 900.0)  # a Retry-After of days is capped at 15 min
        self.assertTrue(r.allowed('transient', 10, 0))
        self.assertFalse(r.allowed('transient', 11, 0))


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
