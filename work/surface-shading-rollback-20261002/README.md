# Surface shading trial rollback

Immediate rollback: uncheck **Rendering → Matte surface (trial)**. This restores
the previous imported mesh materials and face orientation; the choice persists
in this browser across refreshes. Re-enable it to compare.

This trial only changes cloned viewer geometry and materials. Original recordings,
processed meshes, exports and database records are unchanged. No reprocessing.

`main.tsx.before` is the complete pre-trial viewer file. To remove the trial,
restore it to `frontend/src/main.tsx` only if no later edits must be preserved;
otherwise remove the `surfaceAppearance` import, material/orientation branch,
`matteSurface` props/state and trial checkbox selectively. The helper and its test
are `frontend/src/survey/surfaceAppearance.ts` and `surfaceAppearance.test.ts`.
Rebuild and restart the frontend after a code rollback.
