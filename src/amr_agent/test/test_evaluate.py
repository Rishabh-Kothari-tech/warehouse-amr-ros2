from amr_agent.evaluate import CASES, SimBackend, score
from amr_agent.rule_agent import RuleAgent
from amr_agent.tools import ToolExecutor


def test_sim_backend_enforces_mission_rules():
    be = SimBackend(90)
    bad = be.execute_mission([{'station': 'shelf_1', 'action': 'pick', 'item': 'bms_board'}])
    assert not bad['success'] and be.missions == []
    ok = be.execute_mission([{'station': 'shelf_1', 'action': 'pick', 'item': 'bolts_m8'},
                             {'station': 'packing_station', 'action': 'drop', 'item': 'bolts_m8'}])
    assert ok['success'] and be.pos == 'packing_station'


def test_scoring_matches_expectations():
    be = SimBackend(90)
    RuleAgent(ToolExecutor(be)).ask('bring me some bolts')
    assert score(be, {'bolts_m8': 'packing_station'}, False)[0]
    assert not score(be, None, False)[0]
    assert len(CASES) >= 10
