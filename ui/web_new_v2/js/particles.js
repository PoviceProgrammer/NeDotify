// Compatibility facade: all startup/optimization callers share one atmosphere renderer.
import { initAtmosphere, stopAtmosphere, setAtmosphereFps } from './atmosphere-engine.js';

export const initParticles = initAtmosphere;
export const stopParticles = stopAtmosphere;
export const setParticlesFps = setAtmosphereFps;
