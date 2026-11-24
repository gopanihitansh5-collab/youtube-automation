// Original reusable camera/build helper. Local evaluation only, not on production main.
export const clamp01 = x => Math.max(0, Math.min(1, x));
export const smooth = x => { const t=clamp01(x); return t*t*(3-2*t); };
export const ROLE_COLORS = Object.freeze({structure:0x55d6cb,compute:0xffa55c,flow:0xa590ff});
export function animateBuild(parts, seconds, duration=1.1) {
  if (!Number.isFinite(seconds) || !Number.isFinite(duration) || duration<=0) throw Error('Invalid build time');
  for (const part of parts) {
    const progress=smooth((seconds-part.delay)/duration);
    part.m.position.copy(part.end);
    part.m.position.y+=(1-progress)*(part.travel??4);
    part.m.rotation.y=(1-progress)*(part.turn??.5);
    part.m.scale.setScalar(Math.max(.001,progress));
  }
}
export function cameraShot(camera, shots, seconds) {
  if (!Array.isArray(shots) || !shots.length || !Number.isFinite(seconds)) throw Error('Invalid camera plan');
  for(let i=0;i<shots.length;i++) {
    const s=shots[i];
    if(!Number.isFinite(s.start)||!Number.isFinite(s.end)||s.end<=s.start ||
      [s.from,s.to,s.lookFrom,s.lookTo].some(v=>!Array.isArray(v)||v.length!==3||v.some(n=>!Number.isFinite(n))) ||
      (i&&s.start!==shots[i-1].end)) throw Error('Malformed or gapped camera plan');
  }
  const shot=shots.find(s=>seconds>=s.start&&seconds<s.end) || (seconds<shots[0].start?shots[0]:shots.at(-1));
  const t=smooth((seconds-shot.start)/(shot.end-shot.start));
  const mix=(a,b)=>a.map((n,i)=>n+(b[i]-n)*t);
  camera.position.set(...mix(shot.from,shot.to));
  camera.lookAt(...mix(shot.lookFrom,shot.lookTo));
}
