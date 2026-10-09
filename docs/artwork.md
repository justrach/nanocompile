# README artwork

The current README uses `images/readme-cache-banner.png`, a wide editorial banner made with the built-in imagegen tool from the transparent mascot below. It keeps the character, coral coat and golden cache cubes, adds the project name and tagline, and leaves benchmark claims in ordinary text. The previous assets remain available. The banner's alt text includes its wording; the README also retains a text heading.

Final banner edit prompt (edit target and character identity reference: `images/readme-cache-rat-v2.png`):

```text
Use case: precise-object-edit
Asset type: polished wide GitHub README hero banner for nanocompile.
Input image: edit target and character identity reference, the supplied transparent cache-rat illustration.
Primary request: redesign the composition as a refined landscape editorial banner, roughly 2.5:1 aspect ratio. Preserve the same original gray workshop rat, coral coat, wooden parts cabinet, golden artifact cubes and hand-painted ink/gouache character. On the right half, draw a smaller complete rat carefully shelving a golden cube in a compact cabinet; simplify fine strokes for readability. On the left half, generous whitespace with large beautifully typeset lowercase text exactly "nanocompile", and below it the exact subtitle "Reuse the build work you've already done." Use dark warm charcoal lettering, clean restrained readable typography, no distorted letters.
Scene/backdrop: warm ivory paper with extremely subtle grain, a quiet flat background and soft ground shadow. Keep generous margins around all text and the complete illustration.
Style: warm polished original editorial illustration and restrained developer-tool branding, clear at 800 pixels wide.
Constraints: no extra characters, code snippets, performance numbers, logos of other products, badges, watermark, decorative borders or busy props. Preserve character identity and existing coral/gold palette. The title and subtitle must be verbatim and are the only text. This is decorative branding, not a diagram.
```

The earlier README mascot, `images/readme-cache-rat-v2.png`, is a transparent refinement made with the built-in imagegen tool. It preserves the original character and cabinet while removing the paper backdrop for light and dark GitHub themes. The original below remains available. This changes presentation only; benchmark results and compiler behavior are unaffected.

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
