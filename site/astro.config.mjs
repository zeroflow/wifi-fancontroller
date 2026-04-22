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
      title: {
        en: 'ESP32 WiFi Fan Controller',
        de: 'ESP32 WiFi Lüftersteuerung',
      },
      defaultLocale: 'root',
      locales: {
        root: {
          label: 'English',
          lang: 'en',
        },
        de: {
          label: 'Deutsch',
          lang: 'de',
        },
      },
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
          translations: { de: 'Erste Schritte' },
          items: [
            { label: 'Overview', translations: { de: 'Übersicht' }, slug: 'getting-started' },
            { label: 'First Setup', translations: { de: 'Ersteinrichtung' }, slug: 'getting-started/first-setup' },
            { label: 'Home Assistant', slug: 'getting-started/home-assistant' },
            { label: 'Firmware Updates', slug: 'getting-started/firmware-updates' },
            { label: 'Troubleshooting', translations: { de: 'Fehlerbehebung' }, slug: 'getting-started/troubleshooting' },
          ],
        },
        {
          label: 'Reference',
          translations: { de: 'Referenz' },
          items: [
            { label: 'Overview', translations: { de: 'Übersicht' }, slug: 'reference' },
            {
              label: 'Hardware',
              items: [
                { label: 'Overview', translations: { de: 'Übersicht' }, slug: 'reference/hardware' },
                { label: 'Rev 3.x (3.1/3.2/3.3)', slug: 'reference/hardware/rev-3-x' },
                { label: 'Rev 3.0', slug: 'reference/hardware/rev-3-0' },
                { label: 'Rev 2.0', slug: 'reference/hardware/rev-2-0' },
                { label: 'Rev 1.0', slug: 'reference/hardware/rev-1-0' },
              ],
            },
            {
              label: 'Modules',
              translations: { de: 'Module' },
              items: [
                { label: 'Overview', translations: { de: 'Übersicht' }, slug: 'reference/modules' },
                { label: 'Temperature PID', translations: { de: 'Temperatur-PID' }, slug: 'reference/modules/temperature-pid' },
                { label: 'Temperature Linear', translations: { de: 'Temperatur Linear' }, slug: 'reference/modules/temperature-linear' },
                { label: 'Temperature Curve', translations: { de: 'Temperatur-Kurve' }, slug: 'reference/modules/temperature-curve' },
                { label: 'RPM PI Control', translations: { de: 'RPM PI-Regelung' }, slug: 'reference/modules/rpm-pi-control' },
                { label: 'RPM Status LEDs', translations: { de: 'RPM Status-LEDs' }, slug: 'reference/modules/rpm-status-leds' },
                { label: 'Stall Guard', translations: { de: 'Blockierschutz' }, slug: 'reference/modules/stall-guard' },
                { label: 'USR Buttons', translations: { de: 'USR-Tasten' }, slug: 'reference/modules/usr-buttons' },
              ],
            },
            { label: 'Fan Compatibility', translations: { de: 'Lüfter-Kompatibilität' }, slug: 'reference/fan-compatibility' },
          ],
        },
      ],
    }),
  ],
});
