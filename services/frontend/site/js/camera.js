// An orbiting perspective camera for the 3D simulation. Pure functions, no DOM: tested with `node --test`.
// World: millimetres, X to the right, Y away from the viewer, Z up. Yaw 0 looks along +Y.

const FOV = (35 * Math.PI) / 180;
const MAX_PITCH = (89.9 * Math.PI) / 180;
const MIN_PITCH = (-10 * Math.PI) / 180;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

export function makeCamera({ target = [80, 50, 0], distance = 300, yaw = (-35 * Math.PI) / 180, pitch = (40 * Math.PI) / 180 } = {}) {
  // `home` is where the two standard views look at: the middle of the panel
  return { target, home: target, distance, yaw, pitch };
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

/**
 * Moves the view target along the panel by a mouse movement of (dx, dy) pixels on a canvas `height` pixels high, so that the
 * scene follows the mouse. Dragging along the screen up/down moves along the panel (not along Z).
 */
export function pan(camera, dx, dy, height) {
  const { right, forward } = basisOf(camera);
  const perPixel = 1 / (height / 2 / Math.tan(FOV / 2) / camera.distance);
  const flat = normalize([forward[0], forward[1], 0]);
  const depthFactor = 1 / Math.max(0.2, Math.abs(forward[2]));
  const target = [...camera.target];
  for (const axis of [0, 1]) {
    target[axis] += -dx * perPixel * right[axis] + dy * perPixel * depthFactor * flat[axis];
  }
  return { ...camera, target };
}

export function zoom(camera, factor) {
  return { ...camera, distance: clamp(camera.distance * factor, 30, 2000) };
}

// The two views also bring the panel back to the middle.
export const topView = (camera) => ({ ...camera, target: camera.home, yaw: 0, pitch: MAX_PITCH });
export const isoView = (camera) => ({ ...camera, target: camera.home, yaw: makeCamera().yaw, pitch: makeCamera().pitch });

/**
 * The flat (affine) mapping of a triangle in a picture onto a triangle on the screen, as the six numbers of
 * `ctx.setTransform(a, b, c, d, e, f)`. `from` and `to` are three points each: [[x, y], ...] and [{ x, y }, ...].
 */
export function triangleTransform(from, to) {
  const [[x0, y0], [x1, y1], [x2, y2]] = from;
  const ux = x1 - x0;
  const uy = y1 - y0;
  const vx = x2 - x0;
  const vy = y2 - y0;
  const det = ux * vy - uy * vx;
  const dux = to[1].x - to[0].x;
  const duy = to[1].y - to[0].y;
  const dvx = to[2].x - to[0].x;
  const dvy = to[2].y - to[0].y;
  // the matrix M with M * u = du and M * v = dv, that is M = D * S^-1 for S = [u v] and D = [du dv]
  const a = (dux * vy - dvx * uy) / det;
  const c = (dvx * ux - dux * vx) / det;
  const b = (duy * vy - dvy * uy) / det;
  const d = (dvy * ux - duy * vx) / det;
  return [a, b, c, d, to[0].x - a * x0 - c * y0, to[0].y - b * x0 - d * y0];
}
