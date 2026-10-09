# README artwork

The README now uses `images/readme-cache-rat-v2.png`, a transparent refinement made with the built-in imagegen tool. It preserves the original character and cabinet while removing the paper backdrop for light and dark GitHub themes. The original below remains available. This changes presentation only; benchmark results and compiler behavior are unaffected.

Final v2 edit prompt (reference image: `images/readme-cache-rat.png`):

```text
Use case: background-extraction and precise-object-edit.
Asset type: transparent GitHub README mascot for nanocompile.
Edit target: the supplied original workshop rat illustration.
Primary request: refine this into a clean transparent cutout for use on both light and dark README backgrounds. Preserve the same gray rat, coral work coat, wooden cabinet, golden reusable artifact cubes, pose, warm hand-painted ink and gouache aesthetic. Remove the ivory paper background completely with genuine alpha transparency, including between whiskers, tail, feet and cabinet. Keep the entire silhouette and a small natural contact shadow only beneath feet and cabinet. Simplify tiny noisy fur strokes slightly for legibility at 280 pixels, without changing character identity or cabinet contents. Balanced square framing with a little clear transparent margin. No text, logo, watermark, added props or new characters.
```

`images/readme-cache-rat.png` is an original illustration generated with the built-in imagegen tool for nanocompile's README. The workshop-rat theme takes inspiration from [CodeGraff's presentation](https://github.com/justrach/codegraff); this is a new image, not a modified CodeGraff asset. The image is decorative branding, not a technical diagram or performance claim.

Final generation prompt:

```text
Use case: illustration-story
Asset type: square GitHub README mascot illustration for nanocompile, a build cache written in Zig.
Primary request: A companion to CodeGraff's workshop-rat branding: a small clever gray workshop rat wearing a coral work coat, carefully shelving reusable build artifacts as tidy little solid cubes in a compact open wooden parts cabinet. One cube held in its paws, a few matching cubes already stored. Convey saving completed work for reuse.
Style/medium: charming hand-painted editorial illustration, fine ink contours and subtle gouache paper texture, warm restrained colors, polished but not glossy or 3D.
Composition/framing: one complete rat and small cabinet, balanced square composition, generous quiet background margin, recognizable at 280px wide. Simple silhouette and limited props.
Scene/backdrop: clean warm ivory paper background.
Text: none.
Constraints: original illustration; no code snippets, letters, logos, labels, benchmarks, watermarks, gradients or busy background. Keep paws and artifact shapes clear.
```
