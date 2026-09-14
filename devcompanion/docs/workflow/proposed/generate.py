"""Generate proposed BPMN XML/SVG and offline overview; stdlib + Graphviz.

Run: python docs/workflow/proposed/generate.py
The proposed diagrams never overwrite the current-state workflow diagrams.
"""
from pathlib import Path
import html
import subprocess
import textwrap
import xml.etree.ElementTree as E

HERE = Path(__file__).resolve().parent
NS = {'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
      'dc': 'http://www.omg.org/spec/DD/20100524/DC',
      'di': 'http://www.omg.org/spec/DD/20100524/DI'}
for prefix, uri in NS.items():
    E.register_namespace(prefix, uri)


def add(parent, tag, **attrs):
    prefix, name = tag.split(':')
    return E.SubElement(parent, '{%s}%s' % (NS[prefix], name), {k: str(v) for k,v in attrs.items()})


specs = [
 ('start','startEvent','Content event committed',428,30),
 ('save','task','Reconcile disk / overlay; independently enqueue eligible saved tests',315,125),
 ('changed','exclusiveGateway','Effective view changed?',418,265),
 ('same_end','endEvent','No structural work',830,275),
 ('stale','task','Invalidate dependencies and publish outdated findings immediately',315,400),
 ('manifest','task','Debounce; capture immutable effective inputs and search generation',315,540),
 ('analyze','task','Analyze callers using disk + overlay candidates; return result',315,680),
 ('fresh','exclusiveGateway','All inputs and search generation still current?',418,820),
 ('discard','task','Discard obsolete result; persist latest job intent',715,814),
 ('discard_end','endEvent','New work queued',828,935),
 ('commit','task','Commit evidence; remove resolved findings; publish complete set atomically',315,970),
 ('end','endEvent','Ready for voluntary reading',428,1110),
]
flows = [('start','save',''),('save','changed',''),('changed','same_end','no'),
         ('changed','stale','yes'),('stale','manifest',''),('manifest','analyze',''),
         ('analyze','fresh',''),('fresh','discard','no'),('discard','discard_end',''),
         ('fresh','commit','yes'),('commit','end','')]
root = E.Element('{%s}definitions' % NS['bpmn'], {'id':'ProposedDefinitions', 'targetNamespace':'urn:devcompanion:proposed'})
proc = add(root,'bpmn:process',id='Feedback',name='Proposed effective-content feedback',isExecutable='false')
add(proc,'bpmn:documentation').text = ('Proposed v2 design, not implemented. Starts after validated durable acceptance. '
    'Saved-test eligibility is independent of effective-content changes. Saved tests and optional model jobs '
    'execute separately and must pass equivalent final freshness gates. Queue/recovery details are in editor-feedback-design.md. '
    'This process describes logical sequencing; coordinator and worker run asynchronously.')
nodes = {}
for key,kind,label,x,y in specs:
    w,h = (44,44) if kind.endswith('Event') else ((64,64) if kind=='exclusiveGateway' else (270,76))
    node=add(proc,'bpmn:'+kind,id=key,name=label)
    nodes[key]=(node,kind,label,x,y,w,h)
for i,(a,b,label) in enumerate(flows):
    add(nodes[a][0],'bpmn:outgoing').text=f'f{i}'
    add(nodes[b][0],'bpmn:incoming').text=f'f{i}'
diagram=add(root,'bpmndi:BPMNDiagram',id='FeedbackDiagram')
plane=add(diagram,'bpmndi:BPMNPlane',id='FeedbackPlane',bpmnElement='Feedback')
svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1030 1200" role="img" aria-label="Proposed BPMN editor feedback process">',
     '<rect width="1030" height="1200" fill="white"/><defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0 0 L10 4 L0 8" fill="#53677b"/></marker></defs>',
     '<style>text{font:15px Arial;fill:#17334d}</style>']
for i,(a,b,label) in enumerate(flows):
    add(proc,'bpmn:sequenceFlow',id=f'f{i}',sourceRef=a,targetRef=b,name=label)
    ax,ay,aw,ah=nodes[a][3:]; bx,by,bw,bh=nodes[b][3:]
    if abs(ax+aw/2-bx-bw/2)<2:
        pts=[(ax+aw/2,ay+ah),(bx+bw/2,by)]
    else:
        pts=[(ax+aw,ay+ah/2),(bx,by+bh/2)]
    edge=add(plane,'bpmndi:BPMNEdge',id=f'f{i}_di',bpmnElement=f'f{i}')
    for x,y in pts: add(edge,'di:waypoint',x=x,y=y)
    svg.append('<polyline points="%s" fill="none" stroke="#53677b" stroke-width="2" marker-end="url(#arrow)"/>' % ' '.join(f'{x},{y}' for x,y in pts))
    if label:
        x,y=(pts[0][0]+pts[1][0])/2+8,(pts[0][1]+pts[1][1])/2-8
        lab=add(edge,'bpmndi:BPMNLabel'); add(lab,'dc:Bounds',x=x,y=y-15,width=45,height=20)
        svg.append(f'<text x="{x}" y="{y}">{label}</text>')
for key,(node,kind,label,x,y,w,h) in nodes.items():
    shape=add(plane,'bpmndi:BPMNShape',id=key+'_di',bpmnElement=key)
    add(shape,'dc:Bounds',x=x,y=y,width=w,height=h)
    if kind.endswith('Event'):
        svg.append(f'<circle cx="{x+22}" cy="{y+22}" r="21" fill="white" stroke="#207b85" stroke-width="{4 if kind=="endEvent" else 2}"/>')
    elif kind=='exclusiveGateway':
        shape.set('isMarkerVisible','true')
        svg.append(f'<path d="M{x+32},{y} L{x+64},{y+32} L{x+32},{y+64} L{x},{y+32} Z" fill="#fff0d2" stroke="#ad6800" stroke-width="2"/><text x="{x+32}" y="{y+38}" text-anchor="middle">×</text>')
    else:
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#e2f2f2" stroke="#207b85" stroke-width="2"/>')
    external=kind.endswith('Event') or kind=='exclusiveGateway'
    lines=textwrap.wrap(label,28 if external else 33)
    tx,ty,anchor=(x-14,y+18,'end') if external else (x+w/2,y+h/2-(len(lines)-1)*9+5,'middle')
    if external:
        lab=add(shape,'bpmndi:BPMNLabel'); add(lab,'dc:Bounds',x=x-245,y=y,width=230,height=60)
    for j,line in enumerate(lines): svg.append(f'<text x="{tx}" y="{ty+j*18}" text-anchor="{anchor}">{html.escape(line)}</text>')
svg.append('</svg>')
bpmn_svg=''.join(svg)
(HERE/'feedback.svg').write_text(bpmn_svg)
E.indent(root)
E.ElementTree(root).write(HERE/'feedback.bpmn',encoding='utf-8',xml_declaration=True)
c4=subprocess.check_output(['dot','-Tsvg',str(HERE/'containers.dot')],text=True)
c4=c4[c4.index('<svg'):]
(HERE/'containers.svg').write_text(c4)
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Proposed editor feedback loop</title>
<style>body{font:17px/1.65 system-ui;background:#f3f6f8;color:#17334d;margin:0}main{max-width:1150px;margin:auto;padding:32px}h1{line-height:1.2;font-size:38px}section{background:white;padding:24px;margin:24px 0;border:1px solid #d6e1e8;border-radius:12px}svg{width:100%;height:auto;min-width:680px}.diagram{overflow:auto}a{color:#12616d}.tag{color:#ad6800;font-weight:bold}li{margin:9px 0}</style><main>
<p class="tag">PROPOSED DESIGN · 14 September 2026 · Steps 1&ndash;4 implemented; step 5 (restart recovery) is not</p><p style="padding:14px;background:#e2f2f2;border-left:4px solid #207b85;border-radius:5px"><strong>This is the target, kept for comparison.</strong> The unsaved-edit loop it describes is built and verified &mdash; see <a href="../index.html">the current workflow</a> and <a href="../test-results.md">the check run</a>. Two differences in the delivered version: one pane rather than separate Callers and Errors windows, and restart recovery still to do.</p><h1>Unsaved edits → trustworthy findings in Neovim</h1>
<p>Keep disk and editor content separate. Analyze effective editor contents, invalidate old findings immediately, and publish only results whose inputs still match.</p>
<p><a href="../../editor-feedback-design.md">Full design and implementation slices</a> · <a href="../index.html">Current workflow</a> · <a href="feedback.bpmn">BPMN 2.0 XML</a></p>
<section><h2>First milestone</h2><ol><li>Change a Python signature without saving.</li><li>Open Callers: see evidenced mismatches against the current buffers.</li><li>Fix callers without saving: outdated findings disappear after re-analysis.</li><li>Save: run eligible saved-code tests under project policy.</li><li>Restart either side: synchronize buffers and recover work without reviving old findings as fresh.</li></ol>
<p>Proposed scope: one active editor view per workspace; Errors and Callers first; models optional. Testing unsaved code in an isolated copy is a separate scope decision.</p></section>
<section><h2>C4 · Container architecture</h2><div class="diagram">C4_DIAGRAM</div></section>
<section><h2>BPMN 2.0 · Effective-content analysis</h2><p>The process starts after durable acceptance. Saved tests are independently scheduled; they and optional model requests must pass equivalent final freshness checks.</p><div class="diagram">BPMN_DIAGRAM</div></section>
<section><h2>Implementation order</h2><ol><li>Canonical content, explicit disk/overlay views and revision history.</li><li>Coordinator ownership, journal/checkpoint recovery and worker results.</li><li>Atomic findings/status publication and workspace-scoped rendering.</li><li>Separate save eligibility from structural-change detection.</li><li>Versioned diagnostics, then LSP references.</li><li>Optional validated suggestions that never delay deterministic evidence.</li></ol></section>
</main></html>'''
(HERE/'index.html').write_text(page.replace('C4_DIAGRAM',c4).replace('BPMN_DIAGRAM',bpmn_svg))
print('Generated proposed index.html, C4 SVG and BPMN XML/SVG')
