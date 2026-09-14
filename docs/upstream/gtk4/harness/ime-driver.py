#!/usr/bin/python3
"""Send a fixed preedit to a disposable focused text-input, then observe resets."""
import ctypes as C
import json
import select
import time
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
P=C.c_void_p; U=C.c_uint32; I=C.c_int; S=C.c_char_p
class Interface(C.Structure): pass
class Message(C.Structure): pass
IP=C.POINTER(Interface)
Message._fields_=[('name',S),('signature',S),('types',C.POINTER(IP))]
Interface._fields_=[('name',S),('version',I),('method_count',I),('methods',C.POINTER(Message)),('event_count',I),('events',C.POINTER(Message))]
wl=C.CDLL('libwayland-client.so.0')
def fn(name,result,*args):
 f=getattr(wl,name); f.restype=result; f.argtypes=list(args); return f
connect=fn('wl_display_connect',P,S)
roundtrip=fn('wl_display_roundtrip',I,P)
flush=fn('wl_display_flush',I,P)
dispatch=fn('wl_display_dispatch',I,P)
getfd=fn('wl_display_get_fd',I,P)
disconnect=fn('wl_display_disconnect',None,P)
marshal=fn('wl_proxy_marshal_flags',P,P,U,IP,U,U)
listen=fn('wl_proxy_add_listener',I,P,P,P)
interfaces={n:Interface.in_dll(wl,n+'_interface') for n in ('wl_registry','wl_seat','wl_surface','wl_keyboard')}
root=ET.parse(Path(__file__).with_name('input-method-unstable-v2.xml')).getroot()
keep=[]
for node in root.findall('interface'):
 interfaces[node.attrib['name']]=Interface(name=node.attrib['name'].encode(),version=int(node.attrib['version']))
for node in root.findall('interface'):
 iface=interfaces[node.attrib['name']]
 for tag,countfield,arrayfield in [('request','method_count','methods'),('event','event_count','events')]:
  nodes=node.findall(tag); array=(Message*len(nodes))(); keep.append(array)
  for idx,msg in enumerate(nodes):
   args=msg.findall('arg'); types=(IP*len(args))(); keep.append(types)
   sig=msg.attrib.get('since','')
   for j,a in enumerate(args):
    kind=a.attrib['type']; sig+=('?' if a.attrib.get('allow-null')=='true' else '')+{'int':'i','uint':'u','fixed':'f','string':'s','object':'o','new_id':'n','array':'a','fd':'h'}[kind]
    if a.attrib.get('interface') in interfaces: types[j]=C.pointer(interfaces[a.attrib['interface']])
   array[idx]=Message(msg.attrib['name'].encode(),sig.encode(),types)
  setattr(iface,countfield,len(nodes)); setattr(iface,arrayfield,array)

display=connect(None)
assert display,'No Wayland display'
registry=marshal(display,1,C.pointer(interfaces['wl_registry']),1,0,P())
objects={}; callbacks=[]
def callback(restype,*types):
 def wrap(func):
  cb=C.CFUNCTYPE(restype,*types)(func); callbacks.append(cb); return cb
 return wrap
@callback(None,P,P,U,S,U)
def global_(data,reg,name,interface,version):
 key=interface.decode()
 if key in ('wl_seat','zwp_input_method_manager_v2'):
  objects[key]=marshal(reg,0,C.pointer(interfaces[key]),1,0,U(name),S(interface),U(1),P())
@callback(None,P,P,U)
def removed(*args): pass
reg_list=(P*2)(C.cast(global_,P),C.cast(removed,P)); assert listen(registry,reg_list,None)==0
assert roundtrip(display)>=0
assert 'wl_seat' in objects and 'zwp_input_method_manager_v2' in objects
im=marshal(objects['zwp_input_method_manager_v2'],0,C.pointer(interfaces['zwp_input_method_v2']),1,0,P(objects['wl_seat']),P())
word=sys.argv[1] if len(sys.argv)>1 else 'hello'
state={'active':False,'serial':0,'cause':0,'sent':False,'reset':False,'committed':False,'text':None}
events=[]
def send(op,*args): marshal(im,op,None,1,0,*args)
@callback(None,P,P)
def activate(*args): state['active']=True
@callback(None,P,P)
def deactivate(*args): state['active']=False
@callback(None,P,P,S,U,U)
def surrounding(data,obj,text,cursor,anchor): state['text']=(text or b'').decode()
@callback(None,P,P,U)
def cause(data,obj,value): state['cause']=value
@callback(None,P,P,U,U)
def content(*args): pass
@callback(None,P,P)
def done(*args):
 state['serial']+=1
 events.append({'serial':state['serial'],'cause':state['cause'],'text':state['text']})
 if not state['active']: return
 if not state['sent']:
  state['sent']=True; state['sent_at']=time.monotonic()
  data=word.encode(); send(1,S(data),I(len(data)),I(len(data))); send(3,U(state['serial']))
 elif state['cause']==1 and not state['committed'] and not state['reset']:
  state['reset']=True
  send(1,S(b''),I(0),I(0)); send(3,U(state['serial']))
@callback(None,P,P)
def unavailable(*args): state['unavailable']=True
im_list=(P*7)(*[C.cast(f,P) for f in (activate,deactivate,surrounding,cause,content,done,unavailable)])
assert listen(im,im_list,None)==0
start=time.monotonic()
while time.monotonic()-start < 2:
 if state['sent'] and not state['reset'] and not state['committed'] and time.monotonic()-state['sent_at']>0.6:
  state['committed']=True
  send(0,S((word+' ').encode())); send(1,S(b''),I(0),I(0)); send(3,U(state['serial']))
 flush(display)
 if select.select([getfd(display)],[],[],0.05)[0]:
  if dispatch(display)<0: break
print(json.dumps({'state':state,'events':events}),flush=True)
disconnect(display)
assert state['sent'] and not state.get('unavailable'), 'Input method did not activate'
