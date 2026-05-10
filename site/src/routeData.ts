import { defineRouteMiddleware } from '@astrojs/starlight/route-data';

export const onRequest = defineRouteMiddleware((context) => {
  const { entry, head } = context.locals.starlightRoute;

  if (entry.data.template === 'splash') {
    // T-06/D-07: Replace og:type from "article" to "product" on splash pages.
    // Mutating the head array BEFORE Default Head renders avoids duplicate og:type tags.
    const ogTypeIdx = head.findIndex(
      (h: { attrs?: { property?: string } }) => h.attrs?.property === 'og:type'
    );
    if (ogTypeIdx >= 0) {
      head[ogTypeIdx].attrs!.content = 'product';
    } else {
      head.push({ tag: 'meta', attrs: { property: 'og:type', content: 'product' } });
    }
  }
});
