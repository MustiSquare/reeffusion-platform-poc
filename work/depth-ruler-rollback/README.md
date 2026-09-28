# Depth ruler rollback

The Layers > Depth ruler checkbox immediately hides the addition.

The pre-change `frontend/src/main.tsx` is saved as `main.tsx.before` here.
If main.tsx has later edits, preserve those and remove only these four integration changes:

1. The DepthRuler import.
2. The conditional DepthRuler element in ReefScene.
3. The depthRuler property in the Layers initial state.
4. The special display label for the depthRuler layer.

The new implementation is entirely in `frontend/src/survey/DepthRuler.tsx`,
`depthRulerMath.ts` and `depthRulerMath.test.ts`. No survey data, mesh generation,
sea-level calculations or existing geometry have been changed.
