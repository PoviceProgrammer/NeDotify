"""Real atmosphere components under deterministic canvas/audio/RAF fakes."""

from tests.jsdom import run_node, source
from tests.test_visual_effects_lifecycle import HARNESS


def atmosphere_test(script):
    code = f"({source('atmosphere-effects.js')} + '\\n' + {source('atmosphere-engine.js')})"
    exports = "{createAtmosphereEngine, AtmosphereSignal, normalizeAtmosphere, configureAtmosphere, initAtmosphere, stopAtmosphere, destroyAtmosphere, getAtmosphereStatus, setAtmosphereAudioProvider, armAtmosphereAudio}"
    run_node(HARNESS.replace("SOURCE", code).replace("SUBJECT", exports) + script)


def test_disabled_engine_owns_no_canvas_render_work_or_listeners():
    atmosphere_test(r"""
subject.configureAtmosphere({enabled:false});
assert.equal(frames.size,0);
assert.equal(elements.get('particles-bg').children.length,0);
assert.equal(window.listenerCount('resize'),0);
const baseline=operations.length;
tick(5000);
assert.equal(operations.length,baseline);
for(let index=0;index<12;index++){
    subject.configureAtmosphere({enabled:true});
    assert.equal(frames.size,1);
    subject.configureAtmosphere({enabled:false});
    assert.equal(frames.size,0);
    assert.equal(elements.get('particles-bg').children.length,0);
    assert.equal(window.listenerCount('resize'),0);
}
""")


def test_each_weather_layer_draws_and_combinations_share_one_scheduler():
    atmosphere_test(r"""
const engine=subject.createAtmosphereEngine({window,document,random:()=>.5});
for(const name of ['rain','snow','fog','thunderstorm']){
    const effects={rain:false,snow:false,fog:false,thunderstorm:false};effects[name]=true;
    engine.configure({enabled:true,effects,intensity:1,quality:'high',storm:{interval:8}});
    const before=operations.length;
    for(let index=0;index<100;index++)tick(clock+100);
    const draws=operations.slice(before).filter(item=>item.property==='drawImage');
    assert.ok(draws.length>0,name+' must actually draw');
    const expectedWidth={rain:12,snow:48,fog:256,thunderstorm:512}[name];
    assert.ok(draws.some(item=>item.args[0].width===expectedWidth),name+' owns its own painted sprite');
    assert.equal(frames.size,1,'layers must share one scheduler');
}
engine.configure({enabled:true,effects:{rain:true,snow:true,fog:true,thunderstorm:true},quality:'high'});
const before=count('drawImage');tick(clock+100);
assert.ok(count('drawImage')>before);
assert.ok(count('drawImage')-before<200,'combined layers share a bounded draw budget');
assert.equal(frames.size,1);
engine.destroy();assert.equal(frames.size,0);
""")


def test_signal_resolves_low_mid_high_bands_and_releases_on_silence_pause_and_missing_track():
    atmosphere_test(r"""
const config=subject.normalizeAtmosphere({enabled:true,smoothing:.2,max_reaction:.6});
const signal=new subject.AtmosphereSignal();
let range=[1,10];let reads=0;
const audio={playing:true,hasTrack:true,context:{sampleRate:48000},analyser:{frequencyBinCount:1024,fftSize:2048,getByteFrequencyData(bins){reads++;bins.fill(0);for(let index=range[0];index<=range[1];index++)bins[index]=255;}}};
for(let index=0;index<12;index++)signal.sample(audio,config,.1);
assert.ok(signal.value.low>.5);assert.equal(signal.value.mid,0);assert.equal(signal.value.high,0);
const buffer=signal.bins;
range=[11,170];signal.reset();for(let index=0;index<12;index++)signal.sample(audio,config,.1);
assert.equal(signal.bins,buffer,'reuse the frequency buffer');assert.ok(signal.value.mid>.5);assert.equal(signal.value.low,0);
range=[171,600];signal.reset();for(let index=0;index<12;index++)signal.sample(audio,config,.1);
assert.ok(signal.value.high>.5);assert.equal(signal.value.mid,0);assert.ok(signal.value.energy>0);
audio.playing=false;const last=signal.value.high;signal.sample(audio,config,.1);
assert.ok(signal.value.high<last&&signal.value.high>0,'pause releases smoothly');
const pausedReads=reads;for(let index=0;index<80;index++)signal.sample(audio,config,.1);
assert.equal(reads,pausedReads,'paused music must not read FFT data');assert.equal(signal.value.high,0);
audio.playing=true;audio.hasTrack=false;signal.sample(audio,config,.1);assert.equal(reads,pausedReads);
audio.hasTrack=true;config.reactive=false;signal.sample(audio,config,.1);assert.equal(reads,pausedReads);
config.reactive=true;range=[1,600];config.sensitivity=3;config.bass=3;for(let index=0;index<25;index++)signal.sample(audio,config,.1);
assert.ok(signal.value.low<=.6&&signal.value.mid<=.6&&signal.value.high<=.6,'maximum reactivity is a hard bound');
range=[0,0];for(let index=0;index<80;index++)signal.sample(audio,config,.1);assert.equal(signal.value.energy,0,'silence does not preserve stale energy');
""")


def test_low_quality_battery_reduced_motion_and_mac_style_keep_budgets_and_no_flashes():
    atmosphere_test(r"""
const media=surface();media.matches=true;window.matchMedia=()=>media;
window.settings.optimization={performance_preset:'high'};
const engine=subject.createAtmosphereEngine({window,document,random:()=>.5});
engine.configure({enabled:true,quality:'high',effects:{rain:true,thunderstorm:true},storm:{interval:8}});
assert.ok(engine.status().fps<=10);assert.ok(engine.status().qualityScale<=.22);
for(let index=0;index<160;index++)tick(clock+100);
assert.equal(operations.filter(item=>item.property==='drawImage'&&item.args[0].width===512).length,0,'reduced motion suppresses storm flashes');
media.matches=false;emit(media,'change');
const fullScale=engine.status().qualityScale;
emit(window,'nedotify:battery_saver_changed',{isBatteryMode:true});engine.setFps(60);
assert.ok(engine.status().fps<=12&&engine.status().qualityScale<fullScale);
emit(window,'nedotify:battery_saver_changed',{isBatteryMode:false});
window.settings.optimization.performance_preset='low';emit(window,'nedotify:appearance_changed');
assert.ok(engine.status().qualityScale<=.3);
document.documentElement.dataset.uiStyle='macos';emit(window,'nedotify:appearance_changed');
assert.equal(frames.size,1,'macOS has the same enabled weather renderer');
document.body.classList.toggle('mini-player-active',true);emit(window,'nedotify:mini_player_toggled');assert.equal(frames.size,0);
document.body.classList.toggle('mini-player-active',false);emit(window,'nedotify:mini_player_toggled');assert.equal(frames.size,1);
engine.destroy();assert.equal(media.listenerCount('change'),0);
""")


def test_thunder_is_muted_without_explicit_gesture_uses_existing_context_and_cleans_up():
    atmosphere_test(r"""
const engine=subject.createAtmosphereEngine({window,document,random:()=>.5});
engine.configure({enabled:true,effects:{thunderstorm:true},storm:{thunder:true}});
assert.equal(engine.armAudio(),false,'saved thunder option alone never starts sound');
let starts=0,stops=0,connections=0;
function node(){return {connect(){connections++;},disconnect(){},stop(){stops++;},start(){starts++;},gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},frequency:{value:0}};}
const audioContext={state:'running',sampleRate:1000,currentTime:0,destination:{},createBuffer(channels,length){return{getChannelData(){return new Float32Array(length);}}},createBufferSource:node,createBiquadFilter:node,createGain:node};
engine.playThunder({context:audioContext});assert.equal(starts,0);
assert.equal(engine.armAudio({isTrusted:true}),true);
engine.playThunder({context:audioContext});assert.equal(starts,1);assert.equal(connections,3);
engine.destroy();assert.ok(stops>=2);assert.equal(engine.thunderNodes.size,0);
assert.equal(engine.audioArmed,false);assert.equal(engine.thunderBuffer,null);
""")


def test_configuration_clamps_invalid_values_and_missing_effects_never_spin():
    atmosphere_test(r"""
const config=subject.normalizeAtmosphere({enabled:'yes',intensity:Infinity,quality:'ultra',rain:{direction:200,size:-20},storm:{interval:0},effects:{rain:'true'}});
assert.equal(config.enabled,false);assert.equal(config.intensity,.5);assert.equal(config.quality,'auto');assert.equal(config.rain.direction,45);assert.equal(config.rain.size,.2);assert.equal(config.storm.interval,8);
subject.configureAtmosphere({enabled:true,effects:{rain:false,snow:false,fog:false,thunderstorm:false}});
assert.equal(frames.size,0);assert.equal(elements.get('particles-bg').children.length,0);
subject.configureAtmosphere({enabled:true,intensity:0});assert.equal(frames.size,0);
""")
