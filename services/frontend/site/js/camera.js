// An orbiting perspective camera for the 3D simulation. Pure functions, no DOM: tested with `node --test`.
// World: millimetres, X to the right, Y away from the viewer, Z up. Yaw 0 looks along +Y.

const FOV = (35 * Math.PI) / 180;
const MAX_PITCH = (89.9 * Math.PI) / 180;
const MIN_PITCH = (-10 * Math.PI) / 180;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

export function makeCamera({ target = [80, 50, 0], distance = 300, yaw = (-35 * Math.PI) / 180, pitch = (40 * Math.PI) / 180 } = {}) {
  return { target, distance, yaw, pitch };
}

export function eyeOf(camera) {
  const { target, distance, yaw, pitch } = camera;
  return [
    target[0] + distance * Math.sin(yaw) * Math.cos(pitch),
    target[1] - distance * Math.cos(yaw) * Math.cos(pitch),
    target[2] + distance * Math.sin(pitch),
  ];
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const normalize = (a) => {
  const length = Math.hypot(...a);
  return [a[0] / length, a[1] / length, a[2] / length];
};

export function basisOf(camera) {
  const eye = eyeOf(camera);
  const forward = normalize(sub(camera.target, eye));
  const right = normalize(cross(forward, [0, 0, 1]));
  const up = cross(right, forward);
  return { eye, forward, right, up };
}

/** Screen position of a world point: `{ x, y, depth, scale }` (scale = pixels per mm at that point), or null behind the camera. */
export function project(point, basis, width, height) {
  const d = sub(point, basis.eye);
  const depth = dot(d, basis.forward);
  if (depth < 1) return null;
  const scale = height / 2 / Math.tan(FOV / 2) / depth;
  return { x: width / 2 + dot(d, basis.right) * scale, y: height / 2 - dot(d, basis.up) * scale, depth, scale };
}

export function orbit(camera, dYaw, dPitch) {
  return { ...camera, yaw: camera.yaw + dYaw, pitch: clamp(camera.pitch + dPitch, MIN_PITCH, MAX_PITCH) };
}

export function zoom(camera, factor) {
  return { ...camera, distance: clamp(camera.distance * factor, 30, 2000) };
}

export const topView = (camera) => ({ ...camera, yaw: 0, pitch: MAX_PITCH });
export const isoView = (camera) => ({ ...camera, yaw: makeCamera().yaw, pitch: makeCamera().pitch });
