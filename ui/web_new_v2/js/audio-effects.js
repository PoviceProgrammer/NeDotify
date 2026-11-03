// Audio DSP adapted from Riff (MIT), Copyright (c) 2026 rootscripts.
// Upstream 44145b575d2ee498929c2b1ec69cfbd64cf3b239; see licenses/RIFF_LICENSE.txt.
export const AUDIO_DEFAULTS = Object.freeze({speed:1,linkedSpeed:1,pitch:0,volume:1,reverb:0,distortion:0,echo:0,
    hqEnabled:false,engine:'hqmusic-3',vocal:0,air:0,bass:0,low:0,mid:0,high:0});
const bounds={speed:[.5,2],linkedSpeed:[.5,2],pitch:[-12,12],volume:[0,2],reverb:[0,100],distortion:[0,100],echo:[0,100],vocal:[-50,50],air:[-50,50],bass:[-50,50],low:[-12,12],mid:[-12,12],high:[-12,12]};
export function normalizeAudioTools(raw={}) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) raw={};
    const result={...AUDIO_DEFAULTS};
    for(const [key,[min,max]] of Object.entries(bounds)) {
        if (raw[key] === null || raw[key] === '' || typeof raw[key] === 'boolean') continue;
        const value=Number(raw[key]);if(Number.isFinite(value))result[key]=Math.max(min,Math.min(max,value));
    }
    result.hqEnabled=raw.hqEnabled===true;
    if(['hqmusic-3','glyphs-7B','fyro1.1'].includes(raw.engine))result.engine=raw.engine;
    return result;
}
export function audioPlayback(settings) {
    const s=normalizeAudioTools(settings);
    return s.linkedSpeed!==1 || s.pitch!==0
        ? {rate:s.linkedSpeed*Math.pow(2,s.pitch/12),preservesPitch:false}
        : {rate:s.speed,preservesPitch:true};
}
export class RiffAudioRack {
    constructor(ctx) {
        this.ctx=ctx;this.nodes=[];
        const make=type=>{const node=ctx[type]();this.nodes.push(node);return node;};
        const gain=value=>{const node=make('createGain');node.gain.value=value;return node;};
        const filter=(type,freq,q=1)=>{const node=make('createBiquadFilter');node.type=type;node.frequency.value=freq;node.Q.value=q;return node;};
        this.input=gain(1);this.stdInput=gain(1);this.hqInput=gain(0);this.bus=gain(1);
        this.hqCompressor=make('createDynamicsCompressor');
        this.hqBass=filter('lowshelf',80);this.hqVocal=filter('peaking',2500,1.2);this.hqAir=filter('highshelf',9000);
        this.hqSaturation=make('createWaveShaper');this.hqSaturation.oversample='2x';
        this.hqLimiter=make('createDynamicsCompressor');
        Object.assign(this.hqLimiter.threshold,{value:-1});this.hqLimiter.knee.value=0;this.hqLimiter.ratio.value=20;this.hqLimiter.attack.value=.005;this.hqLimiter.release.value=.05;
        const chain=[this.hqInput,this.hqCompressor,this.hqBass,this.hqVocal,this.hqAir,this.hqSaturation,this.hqLimiter,this.bus];
        chain.slice(0,-1).forEach((node,i)=>node.connect(chain[i+1]));
        this.input.connect(this.stdInput);this.stdInput.connect(this.bus);this.input.connect(this.hqInput);
        this.eq=[filter('lowshelf',200),filter('peaking',1000,.9),filter('highshelf',4000)];
        this.bus.connect(this.eq[0]);this.eq[0].connect(this.eq[1]);this.eq[1].connect(this.eq[2]);
        this.effectsInput=this.eq[2];this.dryGain=gain(1);this.masterGain=gain(1);this.fadeGain=gain(1);
        this.effectsInput.connect(this.dryGain);this.dryGain.connect(this.masterGain);this.masterGain.connect(this.fadeGain);this.output=this.fadeGain;
        this.reverbGain=gain(0);this.convolverNode=make('createConvolver');this.convolverNode.buffer=this._createReverbImpulse(ctx);this.convolverNode.connect(this.reverbGain);this.reverbGain.connect(this.masterGain);
        this.distortionNode=make('createWaveShaper');this.distortionNode.oversample='none';this.distortionGain=gain(0);this.distortionNode.connect(this.distortionGain);this.distortionGain.connect(this.masterGain);
        this.delayNode=ctx.createDelay(1);this.nodes.push(this.delayNode);this.delayNode.delayTime.value=.3;this.delayFeedback=gain(.35);this.delayGain=gain(0);
        this.delayNode.connect(this.delayFeedback);this.delayFeedback.connect(this.delayNode);this.delayNode.connect(this.delayGain);this.delayGain.connect(this.masterGain);
        this.routes=new Set();this.apply(AUDIO_DEFAULTS);
    }
    apply(raw) {
        const s=normalizeAudioTools(raw),now=this.ctx.currentTime;
        const smooth=(param,value)=>param.setTargetAtTime(value,now,.015);
        this.hqEnabled=s.hqEnabled;this.hqSettings={engine:s.engine,vocal:s.vocal,air:s.air,bass:s.bass};
        smooth(this.stdInput.gain,s.hqEnabled?0:1);smooth(this.hqInput.gain,s.hqEnabled?1:0);this._applyHqParams();
        ['low','mid','high'].forEach((key,i)=>smooth(this.eq[i].gain,s[key]));
        smooth(this.masterGain.gain,s.volume);smooth(this.reverbGain.gain,s.reverb/100);smooth(this.delayGain.gain,s.echo/100);
        smooth(this.distortionGain.gain,s.distortion/100*.75);smooth(this.dryGain.gain,1-s.distortion/100*.4);
        if(this.lastDistortion!==s.distortion){this.distortionNode.curve=this._makeDistortionCurve(s.distortion);this.lastDistortion=s.distortion;}
        for(const [key,node] of [['reverb',this.convolverNode],['distortion',this.distortionNode],['echo',this.delayNode]]) {
            if(s[key]>0&&!this.routes.has(key)){this.effectsInput.connect(node);this.routes.add(key);}
            else if(s[key]===0&&this.routes.has(key)){this.effectsInput.disconnect(node);this.routes.delete(key);}
        }
    }
    resetFade() {const p=this.fadeGain.gain;p.cancelScheduledValues(this.ctx.currentTime);p.setValueAtTime(1,this.ctx.currentTime);}
    fade(seconds=4) {const p=this.fadeGain.gain;p.cancelScheduledValues(this.ctx.currentTime);p.setValueAtTime(p.value,this.ctx.currentTime);p.linearRampToValueAtTime(0,this.ctx.currentTime+seconds);}
    destroy() {for(const node of this.nodes){try{node.disconnect();}catch{}}this.nodes=[];}
    _createReverbImpulse(ctx) {
      const rate = ctx.sampleRate;
      const len = Math.floor(rate * 0.6);
      const impulse = ctx.createBuffer(2, len, rate);
      const left = impulse.getChannelData(0);
      const right = impulse.getChannelData(1);
      for (let i = 0; i < len; i++) {
        const decay = Math.exp(-i / (rate * 0.15));
        left[i] = (Math.random() * 2 - 1) * decay;
        right[i] = (Math.random() * 2 - 1) * decay;
      }
      return impulse;
    }
    _makeDistortionCurve(amount = 0) {
      const n = 256;
      const curve = new Float32Array(n);
      const k = amount * 2.5;
      for (let i = 0; i < n; i++) {
        const x = (i * 2) / n - 1;
        if (k <= 0) {
          curve[i] = x;
        } else {
          curve[i] = ((3 + k) * x * 20 * (Math.PI / 180)) / (Math.PI + k * Math.abs(x));
        }
      }
      return curve;
    }
    _makeHarmonicCurve(amount = 0) {
      const n = 256;
      const curve = new Float32Array(n);
      const k = amount * 0.02;
      for (let i = 0; i < n; i++) {
        const x = (i * 2) / n - 1;
        curve[i] = x - k * Math.pow(x, 3);
      }
      return curve;
    }
    _applyHqParams() {
      if (!this.hqCompressor) return;

      if (!this.hqEnabled) {
        const ctx = this.ctx;
        if (ctx) {
          if (this.hqBass) this.hqBass.gain.setTargetAtTime(0, ctx.currentTime, 0.02);
          if (this.hqVocal) this.hqVocal.gain.setTargetAtTime(0, ctx.currentTime, 0.02);
          if (this.hqAir) this.hqAir.gain.setTargetAtTime(0, ctx.currentTime, 0.02);
        }
        return;
      }

      let baseBass = 0, baseVocal = 0, baseAir = 0;
      let satAmount = 0;

      this.hqCompressor.threshold.value = -12;
      this.hqCompressor.knee.value = 10;
      this.hqCompressor.ratio.value = 1.5;
      this.hqCompressor.attack.value = 0.01;
      this.hqCompressor.release.value = 0.1;

      switch (this.hqSettings.engine) {
        case 'hqmusic-3':
          satAmount = 0.5;
          break;
        case 'glyphs-7B':
          satAmount = 0.2;
          baseAir = 2.5;
          this.hqAir.frequency.value = 9000;
          break;
        case 'fyro1.1':
          satAmount = 0.2;
          baseBass = 3.0;
          this.hqBass.frequency.value = 80;
          this.hqCompressor.ratio.value = 2.0;
          break;
      }

      this.hqSaturation.curve = this._makeHarmonicCurve(satAmount);

      this.hqBass.gain.value = Math.max(-4, Math.min(4, baseBass + (this.hqSettings.bass * 0.08)));
      this.hqVocal.gain.value = Math.max(-4, Math.min(4, baseVocal + (this.hqSettings.vocal * 0.08)));
      this.hqAir.gain.value = Math.max(-4, Math.min(4, baseAir + (this.hqSettings.air * 0.08)));
    }
}
