import json
import struct
import zlib

from amr_dashboard.dashboard import compute_kpis, pgm_to_png


def test_pgm_to_png_roundtrip(tmp_path):
    w, h = 5, 3
    pix = bytes(range(w * h))
    p = tmp_path / 'm.pgm'
    p.write_bytes(b'P5\n# comment\n%d %d\n255\n' % (w, h) + pix)
    png = pgm_to_png(p)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', png[16:24]) == (w, h)
    idat = png[png.index(b'IDAT') + 4: png.index(b'IEND') - 8]
    raw = zlib.decompress(idat)
    assert raw == b''.join(b'\x00' + pix[r * w:(r + 1) * w] for r in range(h))


def test_kpis_from_decision_log(tmp_path):
    log = tmp_path / 'decisions.jsonl'
    entries = [
        {'seconds': 50, 'trace': [{'tool': 'plan_orders', 'output': {'planned_distance_m': 8, 'naive_distance_m': 16}},
                                  {'tool': 'execute_mission', 'output': {'success': True, 'distance_m': 8, 'duration_s': 45}}]},
        {'seconds': 30, 'trace': [{'tool': 'execute_mission', 'output': {'success': False, 'distance_m': 2, 'duration_s': 27}}]},
        {'seconds': 1, 'trace': [{'tool': 'get_robot_status', 'output': {}}]},
    ]
    log.write_text('\n'.join(json.dumps(e) for e in entries) + '\nnot json\n')
    k = compute_kpis(log)
    assert k['missions'] == 2 and k['success_rate'] == 50 and k['distance_m'] == 10.0
    assert k['avg_mission_s'] == 36 and k['avg_agent_latency_s'] == 4.0 and k['route_saving_pct'] == 50
