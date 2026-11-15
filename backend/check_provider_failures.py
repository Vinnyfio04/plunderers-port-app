"""TEST DATA: one failed transport call becomes an ineligible analysis error."""
from unittest.mock import patch
from backend.decisions import call_decision_provider


def check():
    for failure in (ConnectionResetError('TEST DATA — reset'),ConnectionAbortedError('TEST DATA — aborted')):
        with patch('backend.decisions.urlopen',side_effect=failure) as transport:
            try:
                call_decision_provider({},url='http://127.0.0.1:1/v1',api_key=None,timeout=1)
                raise AssertionError('Transport failure was accepted')
            except ValueError as error:
                assert 'Decision provider request failed' in str(error)
                assert 'TEST DATA' in str(error)
            assert transport.call_count==1,'one call per role; transport failure must not retry'
    print('PASS TEST DATA: reset/aborted provider transport becomes a validation error; exactly one call each')


if __name__=='__main__':
    check()
