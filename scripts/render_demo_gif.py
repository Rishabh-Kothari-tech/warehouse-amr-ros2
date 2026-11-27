#!/usr/bin/env python3
"""Render a recorded mission (scripts/record_demo.py) into an animated GIF for the README.

    python3 scripts/render_demo_gif.py demo.jsonl maps/warehouse_map_v4.yaml docs/media/demo.gif

Needs Pillow and PyYAML. Pose is interpolated between the 1 Hz status samples; playback is sped up.
"""
import bisect
import json
import math
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

W, H = 1000, 560
BG, PANEL, LINE, TEXT, MUTED = '#0e1114', '#161a1f', '#262c34', '#e6e9ed', '#8b94a0'
AMBER, TEAL, GREEN, RED, VIOLET, BLUE = '#f2a93b', '#3cc5b4', '#5cc27a', '#e5615b', '#a68bf0', '#5b8def'
STATION_COL = {'shelf': '#d9772b', 'packing': GREEN, 'shipping': BLUE, 'charger': '#e8c547', 'home': MUTED}
FRAME_DT, FRAME_MS = 0.6, 90          # seconds of recording per frame, display time per frame


def font(size, bold=False, mono=False):
    names = (['DejaVuSansMono-Bold.ttf' if bold else 'DejaVuSansMono.ttf'] if mono else
             [('Inter-SemiBold.otf' if bold else 'Inter-Regular.otf'), ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')])
    for n in names:
        for d in ('/usr/share/fonts/opentype/inter/', '/usr/share/fonts/truetype/dejavu/', ''):
            try:
                return ImageFont.truetype(d + n, size)
            except OSError:
                continue
    return ImageFont.load_default()


def load_map(yaml_path):
    meta = yaml.safe_load(Path(yaml_path).read_text())
    img = Image.open(Path(yaml_path).parent / meta['image']).convert('L')
    lut = [11 if v > 250 else (200 if v < 50 else 22) for v in range(256)]  # free dark, walls light, unknown slate
    return img.point(lut), meta


def lerp_angle(a, b, f):
    d = math.atan2(math.sin(b - a), math.cos(b - a))
    return a + d * f


def main(rec_path, map_yaml, out_path):
    lines = Path(rec_path).read_text().splitlines()
    meta_row, rows = json.loads(lines[0]), [json.loads(l) for l in lines[1:]]
    stations, request = meta_row['stations'], meta_row['request']
    status = [r for r in rows if r['kind'] == 'status' and r['data'].get('x') is not None]
    st_t = [r['t'] for r in status]
    plans = [r for r in rows if r['kind'] == 'plan']
    events = [r for r in rows if r['kind'] == 'event']
    reply = next((r for r in rows if r['kind'] == 'reply'), None)
    intent = next((e for e in events if e['data'].get('type') == 'intent'), None)
    plan_res = next((e for e in events if e['data'].get('type') == 'tool_result' and e['data'].get('name') == 'plan_orders'), None)
    mission = next((e for e in events if e['data'].get('type') == 'tool_call' and e['data'].get('name') == 'execute_mission'), None)
    steps = mission['data']['input']['steps'] if mission else []
    feedback = [e for e in events if e['data'].get('type') == 'feedback']

    gray, m = load_map(map_yaml)
    mw, mh = gray.size
    k = min(600 / mw, 500 / mh)
    map_img = gray.resize((int(mw * k), int(mh * k)), Image.NEAREST).convert('RGB')
    mx, my = 24, 40

    def px(x, y):
        return mx + (x - m['origin'][0]) / m['resolution'] * k, my + (mh - (y - m['origin'][1]) / m['resolution']) * k

    f_title, f_h, f_b, f_s, f_m, f_mb = font(17, True), font(11, True), font(14), font(12), font(12, mono=True), font(13, True, True)
    t_end = (reply['t'] if reply else st_t[-1]) + 2.5
    frames, trail, t = [], [], 0.0
    while t <= t_end:
        i = bisect.bisect_right(st_t, t)
        a = status[max(0, i - 1)]['data']
        b = status[min(i, len(status) - 1)]['data']
        ta, tb = status[max(0, i - 1)]['t'], status[min(i, len(status) - 1)]['t']
        f = 0 if tb == ta else max(0.0, min(1.0, (t - ta) / (tb - ta)))
        x, y = a['x'] + (b['x'] - a['x']) * f, a['y'] + (b['y'] - a['y']) * f
        yaw = lerp_angle(math.radians(a['yaw_deg']), math.radians(b['yaw_deg']), f)
        cur = a if f < 0.5 else b
        if not trail or math.hypot(x - trail[-1][0], y - trail[-1][1]) > 0.04:
            trail.append((x, y))

        im = Image.new('RGB', (W, H), BG)
        d = ImageDraw.Draw(im)
        d.text((24, 12), 'Warehouse AMR  ·  plain-English order → optimised robot mission', font=f_title, fill=TEXT)
        im.paste(map_img, (mx, my))
        if len(trail) > 1:
            d.line([px(*p) for p in trail], fill='#6b4a1c', width=4, joint='curve')
        plan = next((p for p in reversed(plans) if p['t'] <= t), None)
        if plan and cur.get('state') == 'navigating' and len(plan['data']) > 1:
            pts = [px(*p) for p in plan['data']]
            for j in range(0, len(pts) - 1, 2):
                d.line([pts[j], pts[j + 1]], fill=TEAL, width=3)
        for s in stations:
            sx, sy = px(s['x'], s['y'])
            d.ellipse([sx - 7, sy - 7, sx + 7, sy + 7], fill=STATION_COL.get(s['type'], MUTED))
            label = s['name'].replace('_station', '').replace('_dock', '')
            tw = d.textlength(label, font=f_s)
            d.text((sx - tw / 2, sy - 24), label, font=f_s, fill='#cfd5dc')
        rx, ry = px(x, y)
        r = 15
        pts = [(1.25 * r, 0), (-0.8 * r, 0.8 * r), (-0.45 * r, 0), (-0.8 * r, -0.8 * r)]
        c, s_ = math.cos(-yaw), math.sin(-yaw)
        d.polygon([(rx + u * c - v * s_, ry + u * s_ + v * c) for u, v in pts], fill=AMBER)

        # ---- side panel ----
        X0, Y = 648, 40
        d.rounded_rectangle([X0, Y, W - 20, H - 20], 10, fill=PANEL, outline=LINE)
        X = X0 + 16
        Y += 14
        d.text((X, Y), 'ORDER', font=f_h, fill=MUTED)
        Y += 18
        words, line_ = request.split(), ''
        for w_ in words:
            if d.textlength(line_ + ' ' + w_, font=f_b) > 300:
                d.text((X, Y), line_.strip(), font=f_b, fill=AMBER)
                Y, line_ = Y + 19, ''
            line_ += ' ' + w_
        d.text((X, Y), line_.strip(), font=f_b, fill=AMBER)
        Y += 30
        if intent and t >= intent['t']:
            i_ = intent['data']['intent']
            d.text((X, Y), 'ON-DEVICE MODEL (QWEN 2.5 3B) → INTENT', font=f_h, fill=MUTED)
            Y += 18
            d.text((X, Y), f'{i_["intent"]}: {", ".join(i_["items"])}', font=f_m, fill=VIOLET)
            Y += 17
            d.text((X, Y), f'to {i_["destination"] or "packing_station"}', font=f_m, fill=VIOLET)
            Y += 28
        if plan_res and t >= plan_res['t']:
            o = plan_res['data']['output']
            d.text((X, Y), 'ROUTE OPTIMISER (NAV2 PATH LENGTHS)', font=f_h, fill=MUTED)
            Y += 18
            saving = round(100 * (1 - o['planned_distance_m'] / o['naive_distance_m'])) if o.get('naive_distance_m') else 0
            d.text((X, Y), f'{o["planned_distance_m"]:.1f} m vs {o["naive_distance_m"]:.1f} m one-at-a-time', font=f_m, fill=TEAL)
            Y += 17
            d.text((X, Y), f'{saving}% shorter', font=f_mb, fill=TEAL)
            Y += 28
        if steps and mission and t >= mission['t']:
            d.text((X, Y), 'MISSION', font=f_h, fill=MUTED)
            Y += 18
            fb = [e for e in feedback if e['t'] <= t]
            cur_step = fb[-1]['data']['step'] if fb else 1
            finished = reply is not None and t >= reply['t']
            for n_, s in enumerate(steps, 1):
                done = finished or n_ < cur_step
                active = (n_ == cur_step) and not finished
                col = GREEN if done else (AMBER if active else MUTED)
                mark = '✓' if done else ('▶' if active else '·')
                d.text((X, Y), f'{mark} {s["action"]:<5} {s.get("item") or "":<14} @ {s["station"]}', font=f_m, fill=col)
                Y += 17
            Y += 12
        # status block at the bottom
        Yb = H - 112
        d.line([X, Yb - 10, W - 36, Yb - 10], fill=LINE)
        state = cur.get('state', '')
        d.text((X, Yb), state.upper(), font=f_mb, fill={'navigating': TEAL, 'picking': AMBER, 'dropping': AMBER,
                                                         'charging': BLUE, 'error': RED}.get(state, MUTED))
        d.text((W - 36 - d.textlength(f'{t:4.0f} s', font=f_m), Yb), f'{t:4.0f} s', font=f_m, fill=MUTED)
        Yb += 24
        batt = cur.get('battery_pct', 0)
        d.text((X, Yb), f'battery {batt:.0f}%', font=f_s, fill=MUTED)
        d.rounded_rectangle([X + 92, Yb + 4, W - 36, Yb + 12], 4, fill='#1c2128')
        d.rounded_rectangle([X + 92, Yb + 4, X + 92 + (W - 36 - X - 92) * batt / 100, Yb + 12], 4,
                            fill=RED if batt < 25 else (AMBER if batt < 50 else GREEN))
        Yb += 22
        carrying = ', '.join(cur.get('carrying', [])) or 'empty'
        d.text((X, Yb), f'carrying  {carrying}', font=f_s, fill=MUTED)
        if reply and t >= reply['t']:
            Yb += 22
            d.text((X, Yb), reply['data']['reply'].replace('Done: ', '✓ ')[:44], font=f_s, fill=GREEN)
        d.text((24, H - 16), 'ROS 2 Jazzy · Nav2 · SLAM Toolbox · Webots · local LLM via Ollama', font=f_s, fill='#59616c')
        frames.append(im)
        t += FRAME_DT

    pal = [fr.convert('P', palette=Image.ADAPTIVE, colors=96) for fr in frames]
    durations = [FRAME_MS] * (len(pal) - 1) + [2500]
    pal[0].save(out_path, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
    frames[len(frames) // 2].save(str(Path(out_path).with_suffix('.png')))
    print(f'{len(frames)} frames -> {out_path}')


if __name__ == '__main__':
    main(*sys.argv[1:4])
