// Aerotrace flight scene: A320 GLB + procedural landing gear, scroll-driven
// camera that dives onto the main gear and reveals tire wear / damage.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const MODEL_URL = './airbus_a320-200_v2.glb';
const COLORS = { ok: 0x7FE0A8, warn: 0xF2B544, bad: 0xF2706A, scan: 0x5CCFE6 };

// Model units ≈ 3.97 per metre (fuselage 149 units ≈ 37.6 m). Nose points +z, left wing +x.
const CX = -0.9;
const GROUND = -3.6;
const MAIN = { z: 124, track: 15.2, dual: 1.85, R: 2.35, w: 1.75, rim: 1.05 };
const NOSE = { z: 175, dual: 1.05, R: 1.52, w: 0.9, rim: 0.76 };

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a)); return t * t * (3 - 2 * t); };
const V = (x, y, z) => new THREE.Vector3(x, y, z);
// model-viewer style spherical offset: theta around y from +z, phi from +y
const sph = (t, r, th, ph) => {
  th *= Math.PI / 180; ph *= Math.PI / 180;
  return V(t.x + r * Math.sin(ph) * Math.sin(th), t.y + r * Math.cos(ph), t.z + r * Math.sin(ph) * Math.cos(th));
};

// ---------- tire ----------
function tireGeometry(R, w, rim) {
  const a = (R - rim) / 2, c = (R + rim) / 2, b = w / 2, n = 0.42, pts = [];
  for (let i = 0; i <= 64; i++) {
    const t = -Math.PI + (2 * Math.PI * i) / 64, co = Math.cos(t), si = Math.sin(t);
    pts.push(new THREE.Vector2(c + a * Math.sign(co) * Math.abs(co) ** n, b * Math.sign(si) * Math.abs(si) ** n));
  }
  const g = new THREE.LatheGeometry(pts, 128);
  g.rotateZ(-Math.PI / 2); // axle along x
  return g;
}

// u = around the circumference (u=0 faces +z, u≈0.1 is front-lower), v = across the profile (0.5 = tread centre)
function tireTextures({ worn = false, cut = false }) {
  const W = 1024, H = 256, y = v => (1 - v) * H;
  const base = document.createElement('canvas'); base.width = W; base.height = H;
  const g = base.getContext('2d');
  g.fillStyle = '#17181b'; g.fillRect(0, 0, W, H);
  g.fillStyle = worn ? '#2b2b2e' : '#202125'; g.fillRect(0, y(0.6), W, y(0.4) - y(0.6));
  [0.445, 0.483, 0.517, 0.555].forEach(v => {
    g.fillStyle = worn ? '#1c1c1f' : '#08080a';
    g.fillRect(0, y(v) - (worn ? 1 : 2), W, worn ? 2 : 4);
  });
  const emi = document.createElement('canvas'); emi.width = W; emi.height = H;
  const e = emi.getContext('2d');
  e.fillStyle = '#000'; e.fillRect(0, 0, W, H);
  if (worn) {
    const gr = e.createLinearGradient(0, y(0.62), 0, y(0.38));
    gr.addColorStop(0, 'rgba(242,181,68,0)'); gr.addColorStop(0.5, 'rgba(242,181,68,0.9)'); gr.addColorStop(1, 'rgba(242,181,68,0)');
    e.fillStyle = gr; e.fillRect(0, y(0.62), W, y(0.38) - y(0.62));
  }
  if (cut) {
    const x0 = 0.1 * W, path = [];
    for (let i = 0; i <= 10; i++) {
      const t = i / 10;
      path.push([x0 - 22 + t * 44 + (i % 2 ? 7 : -5), y(0.595 - t * 0.19)]);
    }
    const stroke = (ctx, style, width, blur = 0) => {
      ctx.save(); ctx.strokeStyle = style; ctx.lineWidth = width; ctx.lineJoin = 'round';
      ctx.shadowColor = style; ctx.shadowBlur = blur; ctx.beginPath();
      path.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
      ctx.stroke(); ctx.restore();
    };
    stroke(g, '#3a3b3f', 9); stroke(g, '#050505', 4);
    stroke(e, '#F2706A', 5, 18); stroke(e, '#FFD0C8', 2);
  }
  const map = new THREE.CanvasTexture(base); map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = 8;
  const emissiveMap = new THREE.CanvasTexture(emi); emissiveMap.colorSpace = THREE.SRGBColorSpace;
  return { map, emissiveMap };
}

function shellMaterial(color) {
  return new THREE.ShaderMaterial({
    uniforms: { uColor: { value: new THREE.Color(color) }, uReveal: { value: 0 }, uTime: { value: 0 } },
    vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ vUv=uv; vec4 mv=modelViewMatrix*vec4(position,1.); vN=normalize(normalMatrix*normal); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uReveal; uniform float uTime; varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){
        float fres = pow(1. - abs(dot(vN, vV)), 2.4);
        float s = fract(vUv.x - uTime * .22);
        float band = smoothstep(0., .05, s) * (1. - smoothstep(.05, .12, s));
        float rings = step(.93, fract(vUv.y * 14.)) * .35;
        float a = (fres * .95 + band * .8 + rings * .25) * uReveal;
        gl_FragColor = vec4(uColor * a, a);
      }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
  });
}

function makeWheel(spec, risk, opts) {
  const group = new THREE.Group();
  const geo = tireGeometry(spec.R, spec.w, spec.rim);
  const tex = tireTextures(opts);
  const tireMat = new THREE.MeshStandardMaterial({
    map: tex.map, roughness: 0.9, metalness: 0, envMapIntensity: 0.35,
    emissive: 0xffffff, emissiveMap: tex.emissiveMap, emissiveIntensity: 0
  });
  group.add(new THREE.Mesh(geo, tireMat));
  const rimMat = new THREE.MeshStandardMaterial({ color: 0xb9bec6, metalness: 0.85, roughness: 0.3 });
  const rim = new THREE.Mesh(new THREE.CylinderGeometry(spec.rim + 0.12, spec.rim + 0.12, spec.w * 0.82, 48), rimMat);
  rim.rotation.z = Math.PI / 2; group.add(rim);
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(spec.rim * 0.45, spec.rim * 0.55, spec.w * 0.9, 24),
    new THREE.MeshStandardMaterial({ color: 0x2a2d33, metalness: 0.6, roughness: 0.4 }));
  hub.rotation.z = Math.PI / 2; group.add(hub);
  const shell = new THREE.Mesh(geo, shellMaterial(COLORS[risk]));
  shell.scale.setScalar(1.04); shell.renderOrder = 2; group.add(shell);
  return { group, tireMat, shell, R: spec.R, risk };
}

// ---------- gear legs ----------
const strutMat = new THREE.MeshStandardMaterial({ color: 0x9aa1ab, metalness: 0.7, roughness: 0.35 });
const chromeMat = new THREE.MeshStandardMaterial({ color: 0xe6e9ee, metalness: 1, roughness: 0.12 });
function rod(a, b, r, mat) {
  const len = a.distanceTo(b);
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 16), mat);
  m.position.copy(a).add(b).multiplyScalar(0.5);
  m.quaternion.setFromUnitVectors(V(0, 1, 0), b.clone().sub(a).normalize());
  return m;
}

function makeLeg({ x, z, pivotY, axleY, spec, braceDir, wheels }) {
  const pivot = new THREE.Group(); pivot.position.set(x, pivotY, z);
  const L = pivotY - axleY;
  pivot.add(rod(V(0, 0, 0), V(0, -L * 0.62, 0), spec.R * 0.17, strutMat));
  pivot.add(rod(V(0, -L * 0.6, 0), V(0, -L, 0), spec.R * 0.11, chromeMat));
  pivot.add(rod(V(-spec.dual - spec.w * 0.4, -L, 0), V(spec.dual + spec.w * 0.4, -L, 0), spec.R * 0.08, strutMat));
  if (braceDir) pivot.add(rod(V(braceDir * L * 0.5, 0, 0), V(0, -L * 0.45, 0), spec.R * 0.07, strutMat));
  wheels.forEach(({ wheel, side }) => { wheel.group.position.set(side * spec.dual, -L, 0); pivot.add(wheel.group); });
  return pivot;
}

// ---------- scene ----------
function mount(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const canvas = renderer.domElement;
  Object.assign(canvas.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', opacity: '0', transition: 'opacity .8s' });
  host.appendChild(canvas);

  const hud = document.createElement('div');
  Object.assign(hud.style, { position: 'absolute', inset: '0', pointerEvents: 'none', fontFamily: "'Geist Mono',monospace" });
  hud.innerHTML = `
    <div data-vig style="position:absolute;inset:0;opacity:0;background:radial-gradient(ellipse at 50% 50%,rgba(7,9,12,0) 35%,rgba(7,9,12,.85) 100%)"></div>
    <div data-status style="position:absolute;top:22vh;left:0;right:0;text-align:center;font-size:12px;letter-spacing:.14em;color:#5CCFE6;opacity:0"></div>
    <div data-reticle style="position:absolute;left:0;top:0;opacity:0;will-change:transform">
      <div data-box style="position:absolute;transform:translate(-50%,-50%)">
        ${['top:0;left:0;border-width:2px 0 0 2px', 'top:0;right:0;border-width:2px 2px 0 0', 'bottom:0;left:0;border-width:0 0 2px 2px', 'bottom:0;right:0;border-width:0 2px 2px 0']
          .map(s => `<i style="position:absolute;width:18px;height:18px;border-style:solid;border-color:currentColor;${s}"></i>`).join('')}
      </div>
      <div data-label style="position:absolute;white-space:nowrap;background:rgba(13,16,21,.85);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:10px 14px;font-size:11px;line-height:1.6;letter-spacing:.06em;color:#EEF1F4"></div>
    </div>
    <div data-tags></div>`;
  host.appendChild(hud);
  const $ = s => hud.querySelector(s);
  const vig = $('[data-vig]'), status = $('[data-status]'), reticle = $('[data-reticle]'), box = $('[data-box]'), label = $('[data-label]'), tagsEl = $('[data-tags]');

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.9;
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(-80, 140, 220); scene.add(key);
  const under = new THREE.DirectionalLight(0x9fdcff, 1.4); under.position.set(-40, -120, 200); scene.add(under);
  const gearLight = new THREE.PointLight(0xffffff, 0, 60, 1.6); scene.add(gearLight);

  const camera = new THREE.PerspectiveCamera(30, 1, 0.3, 3000);
  const cur = { pos: V(0, 0, 0), tgt: V(0, 0, 0) }, goal = { pos: V(), tgt: V() };
  let progress = 0, ready = false, visible = true, raf = 0, last = performance.now(), keyframes = [];
  let airframeMats = [], wheels = {}, legs = [], laser;

  const resize = () => {
    const w = host.clientWidth || 1, h = host.clientHeight || 1;
    renderer.setSize(w, h, false); camera.aspect = w / h;
    camera.fov = w / h < 1 ? 42 : 30; // portrait phones need a wider lens
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(host); resize();
  const io = new IntersectionObserver(([en]) => { visible = en.isIntersecting; if (visible) loop(); }, { rootMargin: '200px' });
  io.observe(host);

  new GLTFLoader().load(MODEL_URL, gltf => {
    const model = gltf.scene;
    scene.add(model);
    const seen = new Set();
    model.traverse(o => {
      if (!o.isMesh) return;
      (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => {
        if (seen.has(m)) return; seen.add(m);
        airframeMats.push({ m, c: m.color.clone() });
      });
    });
    model.updateMatrixWorld(true);

    const ray = new THREE.Raycaster();
    const hullY = (x, z) => {
      ray.set(V(x, -60, z), V(0, 1, 0));
      const hit = ray.intersectObject(model, true)[0];
      return hit ? hit.point.y : 4;
    };

    const mk = (spec, risk, o = {}) => makeWheel(spec, risk, o);
    wheels = {
      NL: mk(NOSE, 'ok'), NR: mk(NOSE, 'ok'),
      1: mk(MAIN, 'ok'), 2: mk(MAIN, 'bad', { cut: true }), 3: mk(MAIN, 'warn', { worn: true }), 4: mk(MAIN, 'ok')
    };
    const lx = CX + MAIN.track, rx = CX - MAIN.track;
    const mainAxle = GROUND + MAIN.R, noseAxle = GROUND + NOSE.R;
    const legL = makeLeg({ x: lx, z: MAIN.z, pivotY: hullY(lx, MAIN.z) + 0.6, axleY: mainAxle, spec: MAIN, braceDir: -1,
      wheels: [{ wheel: wheels[1], side: 1 }, { wheel: wheels[2], side: -1 }] });
    const legR = makeLeg({ x: rx, z: MAIN.z, pivotY: hullY(rx, MAIN.z) + 0.6, axleY: mainAxle, spec: MAIN, braceDir: 1,
      wheels: [{ wheel: wheels[3], side: 1 }, { wheel: wheels[4], side: -1 }] });
    const legN = makeLeg({ x: CX, z: NOSE.z, pivotY: hullY(CX, NOSE.z) + 0.6, axleY: noseAxle, spec: NOSE,
      wheels: [{ wheel: wheels.NL, side: 1 }, { wheel: wheels.NR, side: -1 }] });
    legs = [
      { g: legL, axis: 'z', stow: -Math.PI / 2 },
      { g: legR, axis: 'z', stow: Math.PI / 2 },
      { g: legN, axis: 'x', stow: -Math.PI / 2 }
    ];
    legs.forEach(l => scene.add(l.g));

    laser = new THREE.Mesh(new THREE.PlaneGeometry(70, 90).rotateX(-Math.PI / 2), new THREE.ShaderMaterial({
      uniforms: { uA: { value: 0 }, uC: { value: new THREE.Color(COLORS.scan) } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }',
      fragmentShader: `uniform float uA; uniform vec3 uC; varying vec2 vUv;
        void main(){ vec2 g=abs(fract(vUv*vec2(28.,36.))-.5); float line=1.-smoothstep(0.,.04,min(g.x,g.y));
          float fade=1.-smoothstep(.25,.5,length(vUv-.5)); float a=(.05+line*.22)*fade*uA; gl_FragColor=vec4(uC*a,a); }`,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide
    }));
    laser.position.set(CX, 0, 148); scene.add(laser);

    scene.updateMatrixWorld(true);
    const wp = k => wheels[k].group.getWorldPosition(V());
    const w2 = wp(2), w3 = wp(3);
    const T0 = V(CX, 13, 118), T1 = V(CX, 3, 134), T2 = V(CX, -0.5, 140);
    keyframes = [
      { p: 0.00, pos: sph(T0, 285, -35, 78), tgt: T0 },
      { p: 0.10, pos: sph(T0, 255, -42, 82), tgt: T0 },
      { p: 0.26, pos: sph(T1, 140, -58, 100), tgt: T1 },
      { p: 0.42, pos: V(CX - 22, -30, 206), tgt: T2 },
      { p: 0.54, pos: V(CX - 19, -27, 198), tgt: T2 },
      { p: 0.64, pos: w3.clone().add(V(10, -4, 21)), tgt: w3 },
      { p: 0.72, pos: w3.clone().add(V(9, -3.6, 19)), tgt: w3 },
      { p: 0.84, pos: w2.clone().add(V(-10, -4, 21)), tgt: w2 },
      { p: 1.00, pos: w2.clone().add(V(-8, -3.2, 16.5)), tgt: w2 }
    ];

    tagsEl.innerHTML = Object.keys(wheels).map(k =>
      `<div data-tag="${k}" style="position:absolute;left:0;top:0;opacity:0;display:flex;align-items:center;gap:6px;font-size:10px;letter-spacing:.1em;color:#EEF1F4;background:rgba(13,16,21,.75);border:1px solid rgba(255,255,255,.12);border-radius:999px;padding:3px 8px 3px 6px;transform:translate(-50%,-50%)"><span style="width:6px;height:6px;border-radius:50%;background:#${COLORS[wheels[k].risk].toString(16)}"></span>${k.length > 1 ? k : 'POS ' + k}</div>`
    ).join('');

    ready = true;
    sample(progress, goal); cur.pos.copy(goal.pos); cur.tgt.copy(goal.tgt);
    canvas.style.opacity = '1';
    loop();
  });

  function sample(p, out) {
    let i = 0;
    while (i < keyframes.length - 2 && p > keyframes[i + 1].p) i++;
    const a = keyframes[i], b = keyframes[i + 1];
    const t = smooth(a.p, b.p, p);
    out.pos.lerpVectors(a.pos, b.pos, t); out.tgt.lerpVectors(a.tgt, b.tgt, t);
  }

  const tmp = V();
  function toScreen(v) {
    tmp.copy(v).project(camera);
    return { x: (tmp.x + 1) / 2 * host.clientWidth, y: (1 - tmp.y) / 2 * host.clientHeight, front: tmp.z < 1 };
  }
  function pxRadius(v, r) {
    const d = camera.position.distanceTo(v);
    return r / (d * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) * host.clientHeight / 2;
  }

  function frame(dt, time) {
    const p = progress;
    sample(p, goal);
    const k = 1 - Math.exp(-dt * 5);
    cur.pos.lerp(goal.pos, k); cur.tgt.lerp(goal.tgt, k);
    camera.position.copy(cur.pos); camera.lookAt(cur.tgt);
    // slow cruise drift before the dive
    const cruise = 1 - smooth(0.2, 0.4, p);
    camera.position.y += Math.sin(time * 0.5) * 2.5 * cruise;

    const ext = smooth(0.1, 0.28, p);
    legs.forEach(l => { l.g.rotation[l.axis] = l.stow * (1 - ext); l.g.visible = ext > 0.02; });

    const focus = smooth(0.3, 0.46, p);
    airframeMats.forEach(({ m, c }) => m.color.copy(c).multiplyScalar(1 - 0.8 * focus));
    gearLight.intensity = focus * 140;
    gearLight.position.copy(camera.position).lerp(cur.tgt, 0.35);
    vig.style.opacity = (focus * 0.9).toFixed(3);

    // scan: grid plane sweeps down through the gear, tire shells light up behind it
    const scanT = smooth(0.44, 0.56, p);
    laser.position.y = THREE.MathUtils.lerp(7, GROUND - 1, scanT);
    laser.material.uniforms.uA.value = Math.sin(Math.PI * clamp((p - 0.43) / 0.15));
    Object.values(wheels).forEach(w => {
      const wy = w.group.getWorldPosition(tmp).y;
      const hit = clamp((laser.position.y < wy + w.R ? 1 : 0) * smooth(0.46, 0.56, p));
      w.shell.material.uniforms.uReveal.value = hit * (w.risk === 'ok' ? 0.55 : 1);
      w.shell.material.uniforms.uTime.value = time;
    });
    wheels[3].tireMat.emissiveIntensity = smooth(0.58, 0.68, p) * (0.55 + 0.25 * Math.sin(time * 2.5));
    wheels[2].tireMat.emissiveIntensity = smooth(0.74, 0.84, p) * (1.4 + 0.8 * Math.sin(time * 6));

    const scanning = p > 0.43 && p < 0.6;
    status.style.opacity = (Math.sin(Math.PI * clamp((p - 0.42) / 0.2))).toFixed(3);
    status.textContent = p < 0.53 ? 'AEROTRACE VISION · SCANNING 6 WHEELS…' : '6 / 6 SCANNED · 2 FLAGGED';

    tagsEl.querySelectorAll('[data-tag]').forEach(el => {
      const k = el.dataset.tag, w = wheels[k], below = k === '2' || k === '3' || k === 'NR';
      const s = toScreen(w.group.getWorldPosition(V()).add(V(0, below ? -(w.R + 1.6) : w.R + 1.4, 0)));
      el.style.opacity = scanning && s.front ? smooth(0.5, 0.53, p).toFixed(3) : '0';
      el.style.left = s.x + 'px'; el.style.top = s.y + 'px';
    });

    const onPos3 = p > 0.6 && p < 0.76, onPos2 = p >= 0.78;
    const tgtWheel = onPos2 ? wheels[2] : wheels[3];
    const ro = onPos2 ? smooth(0.8, 0.86, p) : onPos3 ? smooth(0.62, 0.67, p) * (1 - smooth(0.72, 0.76, p)) : 0;
    reticle.style.opacity = ro.toFixed(3);
    if (ro > 0) {
      const c = tgtWheel.group.getWorldPosition(V()), s = toScreen(c), r = pxRadius(c, tgtWheel.R) * 1.15;
      reticle.style.transform = `translate(${s.x}px,${s.y}px)`;
      reticle.style.color = '#' + COLORS[tgtWheel.risk].toString(16);
      box.style.width = box.style.height = (r * 2) + 'px';
      const leftSide = s.x > host.clientWidth * 0.5;
      Object.assign(label.style, leftSide
        ? { right: (r + 18) + 'px', left: 'auto', top: (-r * 0.6) + 'px' }
        : { left: (r + 18) + 'px', right: 'auto', top: (-r * 0.6) + 'px' });
      label.innerHTML = onPos2
        ? `<div style="color:#F2706A">● POS 2 · MAIN GEAR LH INNER</div><div>CUT DETECTED · 94% CONFIDENCE</div><div style="color:#A7B0BB">Depth 4.1 mm · no dispatch relief</div><div style="color:#F2706A">→ Replace tonight at SGN</div>`
        : `<div style="color:#F2B544">● POS 3 · MAIN GEAR RH INNER</div><div>TREAD 3.2 mm · 38 LANDINGS LEFT</div><div style="color:#A7B0BB">Normal wear · shoulder uneven</div><div style="color:#F2B544">→ Swap at Oct 06 A-check</div>`;
    }
  }

  function loop() {
    cancelAnimationFrame(raf);
    if (!ready || !visible) return;
    raf = requestAnimationFrame(t => {
      const dt = Math.min(0.05, (t - last) / 1000); last = t;
      frame(dt, t / 1000);
      renderer.render(scene, camera);
      loop();
    });
  }

  return {
    setProgress(p) { progress = clamp(p); },
    dispose() { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); renderer.dispose(); host.innerHTML = ''; }
  };
}

window.Aerotrace3D = { mount };
window.dispatchEvent(new Event('aerotrace3d-ready'));
