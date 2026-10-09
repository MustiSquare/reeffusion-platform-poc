import { Box3, MathUtils, Vector3 } from 'three';

/** Fit a bounding sphere in the narrower viewport angle, including portrait views. */
export function viewerFraming(box: Box3, aspect: number, fov = 55, focus?: Vector3) {
  const center = focus?.clone() ?? (box.isEmpty() ? new Vector3() : box.getCenter(new Vector3()));
  const size = box.isEmpty() ? new Vector3(1, 1, 1) : box.getSize(new Vector3());
  const extent = box.isEmpty() ? size.multiplyScalar(.5) : new Vector3(
    Math.max(Math.abs(box.min.x-center.x),Math.abs(box.max.x-center.x)),
    Math.max(Math.abs(box.min.y-center.y),Math.abs(box.max.y-center.y)),
    Math.max(Math.abs(box.min.z-center.z),Math.abs(box.max.z-center.z)),
  );
  const radius = Math.max(extent.length(), 0.5);
  const vertical = MathUtils.degToRad(fov) / 2;
  const horizontal = Math.atan(Math.tan(vertical) * Math.max(aspect, 0.01));
  const distance = radius / Math.sin(Math.min(vertical, horizontal)) * 1.15;
  return { center, radius, distance, minDistance: Math.max(0.05, radius / 1000),
    maxDistance: distance * 10, near: Math.max(0.001, radius / 10000), far: distance * 12 + radius,
    gridSize: Math.max(1, Math.ceil(Math.max(size.x, size.z) / 10) * 10),
    floor: box.isEmpty() ? 0 : box.min.y - radius * 0.02 };
}
