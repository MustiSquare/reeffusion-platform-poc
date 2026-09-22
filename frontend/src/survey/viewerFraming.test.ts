import { describe, expect, it } from 'vitest';
import { Box3, PerspectiveCamera, Vector3 } from 'three';
import { viewerFraming } from './viewerFraming';

describe('dataset camera framing', () => {
  for (const width of [11,50,200,2000]) for (const aspect of [.45,1,2]) {
    it(`fits every corner of a ${width} m dataset at aspect ${aspect}`, () => {
      const box = new Box3(new Vector3(100,-80,200),new Vector3(100+width,-10,200+width));
      const fit = viewerFraming(box,aspect);
      for (const direction of [new Vector3(5,4,7),new Vector3(0,1,.001),new Vector3(1,0,0),new Vector3(0,0,1)]) {
        const camera = new PerspectiveCamera(55,aspect,fit.near,fit.far);
        camera.position.copy(fit.center).addScaledVector(direction.normalize(),fit.distance);
        camera.lookAt(fit.center);camera.updateMatrixWorld();
        for(const x of [box.min.x,box.max.x]) for(const y of [box.min.y,box.max.y]) for(const z of [box.min.z,box.max.z]) {
          const p = new Vector3(x,y,z).project(camera);
          expect(Math.abs(p.x)).toBeLessThan(1);expect(Math.abs(p.y)).toBeLessThan(1);expect(Math.abs(p.z)).toBeLessThan(1);
        }
      }
      expect(fit.maxDistance).toBeGreaterThan(fit.distance);
      expect(fit.far).toBeGreaterThan(fit.maxDistance+fit.radius);
    });
  }
});
