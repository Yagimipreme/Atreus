"""Rebuild the offline report, SVGs and BPMN 2.0 XML: python docs/workflow/generate.py.

Uses Python standard library and Graphviz dot. BPMN SVG and DI share coordinates.
The process model documents current code, and is deliberately not executable.
"""
from pathlib import Path
import html
import subprocess
import textwrap
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
NS = {'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
      'dc': 'http://www.omg.org/spec/DD/20100524/DC',
      'di': 'http://www.omg.org/spec/DD/20100524/DI'}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

def el(parent, tag, **attrs):
    prefix, local = tag.split(':')
    return ET.SubElement(parent, '{%s}%s' % (NS[prefix], local), {k: str(v) for k, v in attrs.items()})

definitions = ET.Element('{%s}definitions' % NS['bpmn'], {
    'id': 'Definitions_devcompanion', 'targetNamespace': 'urn:devcompanion:workflow',
    'exporter': 'devcompanion workflow documentation', 'exporterVersion': '1'})

def process(pid, title, specs, connections, note):
    proc = el(definitions, 'bpmn:process', id=pid, name=title, isExecutable='false')
    el(proc, 'bpmn:documentation').text = note
    nodes = {}
    for key, kind, label, x, y in specs:
        width, height = (44, 44) if kind.endswith('Event') else ((64, 64) if kind == 'exclusiveGateway' else (270, 76))
        node = el(proc, 'bpmn:' + kind, id=key, name=label)
        nodes[key] = (node, kind, label, x, y, width, height)
    for i, (a, b, label) in enumerate(connections):
        fid = f'{pid}_flow_{i}'
        el(nodes[a][0], 'bpmn:outgoing').text = fid
        el(nodes[b][0], 'bpmn:incoming').text = fid
    # Flow node child order is now valid before adding a timer definition.
    for key, (node, kind, *_rest) in nodes.items():
        if kind == 'intermediateCatchEvent':
            timer = el(node, 'bpmn:timerEventDefinition', id=key + '_timer')
            el(timer, 'bpmn:timeDuration').text = 'PT0.4S'
    diagram = el(definitions, 'bpmndi:BPMNDiagram', id=pid + '_diagram', name=title)
    plane = el(diagram, 'bpmndi:BPMNPlane', id=pid + '_plane', bpmnElement=pid)
    ymax = max(v[4] + v[6] for v in nodes.values()) + 70
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1020 {ymax}" role="img" aria-label="{html.escape(title)}">',
           '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8" fill="#53677b"/></marker></defs>',
           '<style>text{font:15px Arial;fill:#17334d}.label{font-size:13px}</style>']
    for i, (a, b, label) in enumerate(connections):
        fid = f'{pid}_flow_{i}'
        el(proc, 'bpmn:sequenceFlow', id=fid, sourceRef=a, targetRef=b, name=label)
        av, bv = nodes[a], nodes[b]
        ax, ay, aw, ah = av[3:]; bx, by, bw, bh = bv[3:]
        if a == 'b_no' and b == 'b_merge':
            # Bypass the replay-skip task without crossing it or sharing its flow.
            pts = [(ax+aw, ay+ah/2), (995, ay+ah/2), (995, by+16), (bx+48, by+16)]
        elif ax == bx or abs(ax + aw/2 - bx - bw/2) < 2:
            pts = [(ax+aw/2, ay+ah), (bx+bw/2, by)]
        elif abs(ay + ah/2 - by - bh/2) < 3:
            pts = [(ax+aw, ay+ah/2), (bx, by+bh/2)] if bx > ax else [(ax, ay+ah/2), (bx+bw, by+bh/2)]
        elif bx > ax:
            pts = [(ax+aw, ay+ah/2), (bx+bw/2, ay+ah/2), (bx+bw/2, by)]
        else:
            pts = [(ax+aw/2, ay+ah), (ax+aw/2, by+bh/2), (bx+bw, by+bh/2)]
        edge = el(plane, 'bpmndi:BPMNEdge', id=fid+'_di', bpmnElement=fid)
        for x,y in pts:
            el(edge, 'di:waypoint', x=x, y=y)
        svg.append('<polyline points="%s" fill="none" stroke="#53677b" stroke-width="1.7" marker-end="url(#arrow)"/>' % ' '.join(f'{x},{y}' for x,y in pts))
        if label:
            x, y = (pts[0][0]+pts[1][0])/2+7, (pts[0][1]+pts[1][1])/2-7
            lab = el(edge, 'bpmndi:BPMNLabel')
            el(lab, 'dc:Bounds', x=x, y=y-14, width=140, height=20)
            svg.append(f'<text class="label" x="{x}" y="{y}">{html.escape(label)}</text>')
    for key, (node, kind, label, x, y, w, h) in nodes.items():
        shape = el(plane, 'bpmndi:BPMNShape', id=key+'_di', bpmnElement=key)
        if kind == 'exclusiveGateway':
            shape.set('isMarkerVisible', 'true')
        el(shape, 'dc:Bounds', x=x, y=y, width=w, height=h)
        if kind.endswith('Event'):
            svg.append(f'<circle cx="{x+w/2}" cy="{y+h/2}" r="21" fill="white" stroke="#207b85" stroke-width="{4 if kind == "endEvent" else 2}"/>')
            if kind == 'intermediateCatchEvent':
                svg.append(f'<circle cx="{x+22}" cy="{y+22}" r="17" fill="none" stroke="#207b85"/><circle cx="{x+22}" cy="{y+22}" r="12" fill="none" stroke="#207b85"/><path d="M{x+22},{y+12} v10 h8" fill="none" stroke="#207b85"/>')
        elif kind == 'exclusiveGateway':
            svg.append(f'<path d="M{x+32},{y} L{x+w},{y+32} L{x+32},{y+h} L{x},{y+32} Z" fill="#fff0d2" stroke="#ad6800" stroke-width="2"/><text x="{x+32}" y="{y+38}" text-anchor="middle">×</text>')
        else:
            svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#e2f2f2" stroke="#207b85" stroke-width="2"/>')
        if kind.endswith('Event') or kind == 'exclusiveGateway':
            tx, ty = x-14, y+18
            lines = textwrap.wrap(label, 27)
            anchor = 'end'
            lab = el(shape, 'bpmndi:BPMNLabel')
            el(lab, 'dc:Bounds', x=x-230, y=y, width=215, height=50)
        else:
            lines = textwrap.wrap(label, 32)
            tx, ty, anchor = x+w/2, y+h/2-(len(lines)-1)*9+5, 'middle'
        for j, line in enumerate(lines):
            svg.append(f'<text x="{tx}" y="{ty+j*18}" text-anchor="{anchor}">{html.escape(line)}</text>')
    svg.append('</svg>')
    rendered = ''.join(svg)
    (HERE / (pid+'.svg')).write_text(rendered)
    return rendered

intake = process('intake', 'BPMN 2.0 · Event intake', [
    ('i_start','startEvent','Event received',428,25),
    ('i_session','exclusiveGateway','Session event? goal / dismiss / request / lsp_result / session_end',418,110),
    ('i_session_do','task','Record it; session_end drops that editor\'s overlays and requeues those paths',700,104),
    ('i_session_end','endEvent','Published; no file analysis',813,225),
    ('i_light','exclusiveGateway','Cursor or diagnostics?',418,250),
    ('i_light_do','task','Append event; store diagnostics for republication',700,244),
    ('i_light_end','endEvent','No investigation',813,365),
    ('i_content','task','Resolve content: editor text (hash verified) → recorded SHA → disk. Origin is editor when the buffer is dirty',315,390),
    ('i_missing','exclusiveGateway','Content missing?',418,530),
    ('i_delete','task','Log file_deleted; forget any overlay',700,524),
    ('i_delete_end','endEvent','Deletion handling stops',813,640),
    ('i_snap','task','Seed Git HEAD baseline on first live sight; snapshot with origin; record overlay or disk revision; log without text',315,660),
    ('i_same','exclusiveGateway','Same bytes AND same origin?',418,810),
    ('i_same_end','endEvent','No work',813,820),
    ('i_queue','task','Submit path, SHA and origin to scheduler',315,940),
    ('i_changed','exclusiveGateway','Bytes actually changed?',418,1080),
    ('i_saved_end','endEvent','Save of already-analysed bytes; tools rerun, nothing invalidated',813,1090),
    ('i_stale','task','Mark dependent claims stale and requeue their defining files',315,1210),
    ('i_new','task','Requeue any claim whose callee this file now names but never depended on',315,1350),
    ('i_end','endEvent','Event handled; worker runs separately',428,1490),
], [('i_start','i_session',''),('i_session','i_session_do','yes'),('i_session_do','i_session_end',''),
    ('i_session','i_light','no'),('i_light','i_light_do','yes'),('i_light_do','i_light_end',''),
    ('i_light','i_content','no'),('i_content','i_missing',''),('i_missing','i_delete','yes'),
    ('i_delete','i_delete_end',''),('i_missing','i_snap','no'),('i_snap','i_same',''),
    ('i_same','i_same_end','yes'),('i_same','i_queue','no'),('i_queue','i_changed',''),
    ('i_changed','i_saved_end','no'),('i_changed','i_stale','yes'),('i_stale','i_new',''),('i_new','i_end','')],
    'Scope: accepted engine Event under contract v2, not all contract messages. The editor sends canonical buffer text; the engine recomputes its hash rather than trusting the declared one, reports a mismatch, and uses the bytes that arrived. Origin decides everything downstream: editor content exists only in a buffer, disk content is what shelling-out tools can see. A save that changes no bytes still passes through scheduling, because the same content becoming visible to pytest and rg is news. Scheduling submission is asynchronous in watch; it is not a BPMN sequence flow into the worker process.')

bundle = process('bundle', 'BPMN 2.0 · Scheduled investigation bundle', [
    ('b_start','startEvent','Path bundle pending',428,25),
    ('b_wait','task','Wait until debounce due; newer submission replaces pending bundle',315,120),
    ('b_base','exclusiveGateway','Content came from the editor?',418,260),
    ('b_base_e','task','Baseline is the last saved content: one edit, not a stream of drafts',700,254),
    ('b_base_d','task','Baseline is the previous saved content',60,254),
    ('b_detect','task','Record superseded bundles; compare baseline and current',315,400),
    ('b_tasks','task','For each detected task, run investigation process below; store evidence',315,540),
    ('b_tests','exclusiveGateway','Changed/removed names AND tests enabled AND content is on disk?',418,690),
    ('b_no','task','No test run; unsaved content is not something pytest can import',700,684),
    ('b_replay','exclusiveGateway','Replay mode?',418,830),
    ('b_skip','task','Record skipped: replay never executes tests',700,824),
    ('b_run','task','Run pytest -q -x on files mentioning names; label evidence saved-revision-only and name uncovered buffers',315,970),
    ('b_merge','exclusiveGateway','',418,1130),
    ('b_present','task','Write board.md + quickfix.txt; publish findings.jsonl + engine.json atomically; record timings',315,1270),
    ('b_end','endEvent','Results ready for voluntary reading',428,1420),
], [('b_start','b_wait',''),('b_wait','b_base',''),('b_base','b_base_e','yes'),('b_base','b_base_d','no'),
    ('b_base_e','b_detect',''),('b_base_d','b_detect',''),('b_detect','b_tasks',''),('b_tasks','b_tests',''),
    ('b_tests','b_no','no'),('b_tests','b_replay','yes'),('b_no','b_merge',''),
    ('b_replay','b_skip','yes'),('b_replay','b_run','no'),('b_skip','b_merge',''),
    ('b_run','b_merge',''),('b_merge','b_present',''),('b_present','b_end','')],
    'One scheduler worker. The 400 ms debounce is reset per submitted path; ingest/replay drain immediately. The baseline choice is the difference between useful and noisy: an unsaved buffer is compared against the last save, so an edit typed across several debounce windows reads as one change. Tests run after all tasks, once per bundle, and only for content that is on disk — pytest imports the working tree and cannot see a buffer. Test results include passed, failed, none, unavailable and timeout. No parallel gateway: tests and suggestions execute synchronously in this worker.')

investigation = process('investigation', 'BPMN 2.0 · One detected task', [
    ('t_start','startEvent','Detected task',428,25),
    ('t_kind','exclusiveGateway','Signature change or removal?',418,130),
    ('t_status','task','Store noop, unknown_intent or new_function record',700,124),
    ('t_status_end','endEvent','Task complete',813,235),
    ('t_cand','task','Candidates: rg over the working tree PLUS every unsaved buffer naming the callee',315,265),
    ('t_call','task','Read each candidate at its effective revision; tree-sitter judges the arguments',315,410),
    ('t_stale','exclusiveGateway','Input stale during caller scan?',418,555),
    ('t_cancel','task','Store cancelled evidence',700,549),
    ('t_cancel_end','endEvent','Task abandoned',813,665),
    ('t_removal','task','For removed functions, mark found sites breaks; build claim; label whether it rests on a buffer',315,695),
    ('t_model','exclusiveGateway','Model configured AND breaking sites?',418,845),
    ('t_suggest','task','Request one sentence; failure gives no suggestion',700,839),
    ('t_merge','exclusiveGateway','',418,985),
    ('t_store','task','Store SHA dependencies and evidence; suppress identical fresh fingerprint',315,1125),
    ('t_end','endEvent','Return to bundle',428,1265),
], [('t_start','t_kind',''),('t_kind','t_status','no'),('t_status','t_status_end',''),
    ('t_kind','t_cand','yes'),('t_cand','t_call',''),('t_call','t_stale',''),('t_stale','t_cancel','yes'),
    ('t_cancel','t_cancel_end',''),('t_stale','t_removal','no'),('t_removal','t_model',''),
    ('t_model','t_suggest','yes'),('t_model','t_merge','no'),('t_suggest','t_merge',''),
    ('t_merge','t_store',''),('t_store','t_end','')],
    'Detailed activity for each detected task, invoked by the bundle task. rg reads files, so a call typed a second ago is invisible to it; unsaved buffers are added to the candidate set and every candidate is then read at its effective revision. The fingerprint includes the revision label, so a claim that moves from buffer to saved file is an update rather than an unchanged record. The detector returns unknown_intent on current parse errors; noop on first observation, invalid previous baseline or no signature change. New functions do not generate tests. Model payload currently includes up to 12 sites regardless of verdict. No final freshness gate exists after model/test execution.')

ET.indent(definitions)
ET.ElementTree(definitions).write(HERE/'current-workflow.bpmn', encoding='utf-8', xml_declaration=True)

c4 = []
for name in ('context', 'containers', 'components'):
    svg = subprocess.check_output(['dot', '-Tsvg', str(HERE/(name+'.dot'))], text=True)
    svg = svg[svg.index('<svg'):]
    (HERE/(name+'.svg')).write_text(svg)
    c4.append(svg)

body = (HERE/'report-body.html').read_text()
for key, diagram in zip(('CONTEXT','CONTAINERS','COMPONENTS','INTAKE','BUNDLE','INVESTIGATION'), c4+[intake,bundle,investigation]):
    body = body.replace('{{'+key+'}}', diagram)
(HERE/'index.html').write_text(body)
print('Generated index.html, 6 SVG diagrams and current-workflow.bpmn')
