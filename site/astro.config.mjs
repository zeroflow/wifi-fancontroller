import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightBlog from 'starlight-blog';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://fancontroller.arthofer.dev',
  vite: { plugins: [tailwindcss()] },
  integrations: [
    starlight({
      // Starlight v0.38 route middleware registration
      components: {
        Head: './src/components/StarlightHead.astro',
      },
      routeMiddleware: './src/routeData.ts',
      plugins: [starlightBlog()],
      title: 'ESP32 WiFi Fan Controller',
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/zeroflow/wifi-fancontroller',
        },
      ],
      favicon: '/favicon.ico',
      customCss: ['./src/styles/global.css'],
      sidebar: [
        {
          label: 'Getting Started',
          autogenerate: { directory: 'getting-started' },
        },
        {
          label: 'Reference',
          items: [
            { label: 'Overview', slug: 'reference' },
            {
              label: 'Hardware',
              autogenerate: { directory: 'reference/hardware' },
            },
            {
              label: 'Modules',
              autogenerate: { directory: 'reference/modules' },
            },
            {
              label: 'Qwiic / STEMMA QT',
              items: [
                { label: 'General', slug: 'reference/qwiic' },
                { label: 'Combining Modules', slug: 'reference/qwiic/combining' },
                {
                  label: 'Expansion Board Examples',
                  autogenerate: { directory: 'reference/qwiic/examples' },
                },
              ],
            },
            { slug: 'reference/fan-compatibility' },
            { slug: 'reference/web-server' },
          ],
        },
      ],
    }),
  ],
});
