#!/usr/bin/env python3
"""Audit actual saved native state coverage without inventing candidate payloads."""
from collections import Counter,defaultdict
import hashlib
import json
import re
import struct
import zstandard
from conformance import CHECKOUT,DATA,Native,checked,sha,need,load
from runtime_events import events


def audit():
    native=Native();desc=native.producer["ordered_stream"]
    path=checked(native.directory/desc["path"],desc["sha256"])
    decoder=zstandard.ZstdDecompressor().decompressobj();digest=hashlib.sha256();size=0;pending=b"";counts=Counter();keys=defaultdict(set)
    selected={"native_state","scene_pass","scene_state","node_rng","scene_anchor_locals"};projection=hashlib.sha256()
    samples={}
    with path.open("rb") as stream:
        while block:=stream.read(1<<20):
            raw=decoder.decompress(block);need(not decoder.unused_data,"native trailing stream")
            digest.update(raw);size+=len(raw)
            lines=(pending+raw).split(b"\n");pending=lines.pop()
            for line in lines:
                match=re.search(rb'"event":"([^"]+)"',line);need(match is not None,"native event missing")
                name=match[1].decode()
                if name=="backend_probe":
                    need("seq" not in json.loads(line),"sequenced backend probe")
                    name="out_of_band_backend_probe" # Same classification as accepted review_full.py.
                counts[name]+=1
                if name in selected:
                    item=json.loads(line);keys[name].update(item);projection.update(line+b"\n")
                    samples.setdefault(name,item)
    need(decoder.eof and not pending and size==desc["decoded_bytes"] and digest.hexdigest()==desc["decoded_sha256"],"native stream identity")
    need(dict(counts)==desc["event_counts"],"native event coverage "+str({k:(counts.get(k),desc['event_counts'].get(k)) for k in counts.keys()|desc['event_counts'].keys() if counts.get(k)!=desc['event_counts'].get(k)}))
    job=DATA/"verification/rust/live-d26-full01";state=load(job/"state.json")
    checked(job/"output/events.bin",state["output"]["output/events.bin"]["sha256"])
    initial=next(payload for kind,payload in events(job/"output/events.bin") if kind==1)
    payloads={}
    for role,path in native.states.items():
        raw=path.read_bytes();status="NO_CANDIDATE_PHASE_PAYLOAD"
        if role=="first-query/physics":
            need(initial[28:]==raw,"initial physics differs");status="EXACT_OBSERVED_NATIVE_LAYOUT"
        if role=="first-query/previous-seconds":status="SOURCE_BACKED_ZERO_INITIALIZATION; NOT_SEPARATELY_OBSERVED"
        payloads[role]=dict(bytes=len(raw),sha256=sha(path),all_zero=not any(raw),status=status)
    seed=native.states["prethread/rng"].read_bytes()[16:32]
    result=dict(schema="eidolon-rust-state-scope-1",native_stream_sha256=desc["sha256"],decoded_sha256=digest.hexdigest(),
                event_counts=dict(counts),selected_field_names={k:sorted(v) for k,v in keys.items()},projection_sha256=projection.hexdigest(),
                initial_payloads=payloads,observed_candidate_payloads=1,total_native_payloads=7,
                native_prethread_seed_i64=list(struct.unpack("<2q",seed)),native_prethread_tick=struct.unpack("<I",native.states["prethread/tick"].read_bytes())[0],
                source_correspondence={"audio_seed":"src/audio/runtime.rs: seed [1,31337], thread-local Runtime allocation",
                                       "audio_tick":"src/audio/runtime.rs: zeroed State then tick=1 inside synthesis thread",
                                       "physics":"src/engine.rs: Engine::default constructs initialized records; native entry dump precedes native initialization",
                                       "previous_seconds":"src/engine.rs: default +0; no separate runtime payload"},
                source_sha256={p:sha(CHECKOUT/p) for p in ("src/audio/runtime.rs","src/engine.rs","src/physics.rs","src/observe.rs")},
                later_physics_vector_available=False,available_native_uniforms=["uTimeResolution","uClouds"],
                uniform_value_event_count=counts["scene_pass"],candidate_uniform_payload_available=False,
                remaining="Entry/prethread global storage phases differ from Rust object/thread initialization. Complete internal-layout equivalence is not established. Native later physics/curve-uniform vectors are absent; no additional native run is justified merely to repeat existing fields.",
                production_accepted=False)
    output=CHECKOUT/"artifacts/verification/rust/state-scope.json";output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(dict(observed_payloads=1,native_payloads=7,later_physics=False,native_uniform_observations=counts["scene_pass"])))


if __name__=="__main__":audit()
