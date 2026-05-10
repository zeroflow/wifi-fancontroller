/**
 * build-og-homepage.mjs - Generate 1200x630 OG image from board photo
 * Usage: node site/scripts/build-og-homepage.mjs
 *
 * Resizes board_rev3.3_front.jpg to 1200x630 (cover crop) for use as
 * the language-neutral homepage OG image.
 */

import sharp from 'sharp';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const siteDir = join(__dirname, '..');

const inputPath = join(siteDir, 'public', 'images', 'board_rev3.3_front.jpg');
const outputPath = join(siteDir, 'public', 'og', 'homepage.png');

console.log('Generating OG image...');
console.log(`Input:  ${inputPath}`);
console.log(`Output: ${outputPath}`);

await sharp(inputPath)
  .resize(1200, 630, {
    fit: 'cover',
    position: 'centre',
  })
  .png({ quality: 90, compressionLevel: 8 })
  .toFile(outputPath);

const { size } = (await import('fs')).statSync(outputPath);
console.log(`Done. File size: ${(size / 1024).toFixed(1)}KB`);
console.log(`Output: ${outputPath}`);
