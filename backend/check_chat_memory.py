"""Offline SDK checks for conversation/ticker/mode isolation and agent context."""
import asyncio
import os
from unittest.mock import patch
from uuid import uuid4

from backend.chat_agent import TestChatModel, conversations, run_chat


async def check():
    conversation = str(uuid4())
    observed = []
    original = TestChatModel.get_response

    async def observe(self, *args, **kwargs):
        observed.append(args[0] if args else kwargs['system_instructions'])
        return await original(self, *args, **kwargs)

    def assess(chart):
        return dict(snapshot=dict(symbol=chart['symbol'], interval='1m', cutoff=chart['cutoff'],
                                 snapshot_id=chart['snapshot_id'], python_crossover=dict(signal='none')),
                    answers=[dict(name='action', choice='wait', probability=.64)],
                    reviewer_answers=[dict(name='verdict', choice='accept')], eligibility_reasons=[])

    async def turn(symbol, mode, time, message='Assess and compare this chart.', chat_id=conversation):
        return await run_chat(message, dict(symbol=symbol, data_mode=mode, cutoff=time,
                                           snapshot_id=f'{symbol}-{mode}-{time}'), assess, chat_id)

    with patch.dict(os.environ, CHAT_PROVIDER='test'), patch.object(TestChatModel, 'get_response', observe):
        first = await turn('AAA', 'live', 'earlier')
        assert first['assessment']['previous_assessment'] is None
        assert 'No earlier assessment exists' in first['response']
        assert (await turn('BBB', 'live', 'later'))['assessment']['previous_assessment'] is None
        assert (await turn('AAA', 'replay', 'later'))['assessment']['previous_assessment'] is None
        rules = await turn('AAA', 'live', 'later', 'What does WAIT mean in this app?')
        assert [call['name'] for call in rules['tools']] == ['explain_decision_rules']
        failure = await turn('AAA', 'live', 'later', 'Assess chart tool failure')
        assert failure['assessment']['status'] == 'error'
        compared = await turn('AAA', 'live', 'later')
        assert compared['assessment']['previous_assessment']['snapshot_id'] == first['assessment']['snapshot_id']
        assert first['assessment']['snapshot_id'] in observed[-1], 'agent receives the earlier tool result'
        assert 'earlier' in compared['response'] and 'later' in compared['response']
        fresh = await turn('AAA', 'live', 'later', chat_id=str(uuid4()))
        assert fresh['assessment']['previous_assessment'] is None
    conversations.clear()
    print('PASS SDK conversation memory: full prior tool result reaches agent; ticker/mode/New chat isolation; rules and failure preserve earlier result.')


if __name__ == '__main__':
    asyncio.run(check())
