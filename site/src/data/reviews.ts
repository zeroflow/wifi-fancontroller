// Single source of truth for customer reviews.
// Consumed by:
//   - site/src/components/ProductSchema.astro (JSON-LD reviewBody / reviewRating / author / datePublished / name)
//   - site/src/components/ReviewStrip.astro (visible text block, D-03 minimal review block)
//
// When updating, the `body` field MUST match verbatim the Tindie-published quote.
// The `displayQuote` field is the <=120-char excerpt used in the visible block (Gemini review 14-REVIEWS.md Suggestion 1).

export interface Review {
  /** Reviewer display name (Schema.org Person.name). */
  reviewer: string;
  /** Numeric rating 0-5, supports halves (4.5). */
  rating: number;
  /** Full review text from Tindie - used by ProductSchema.astro JSON-LD reviewBody. */
  body: string;
  /** <=120-char excerpt used by ReviewStrip.astro visible block (D-03 constraint). */
  displayQuote: string;
  /** Marketplace source of the review. Always "Tindie" for current reviews. */
  source: string;
  /** Date published YYYY-MM-DD - used by ProductSchema.astro JSON-LD datePublished. */
  datePublished: string;
  /** Schema.org review title - used by ProductSchema.astro JSON-LD name. */
  title: string;
}

export const reviews: ReadonlyArray<Review> = [
  {
    reviewer: "Lila",
    rating: 5,
    body: "Product works amazingly and is even better than expected. Creator is quick to reply to issues and questions. Shipping was timely and was even faster than expected. Would buy again. Love ready-made ESPHOME products like this. Used mine in a DIY air filter.",
    displayQuote: "Product works amazingly and is even better than expected. Creator is quick to reply to issues and questions.",
    source: "Tindie",
    datePublished: "2026-02-03",
    title: "Amazing DIY Product!",
  },
  {
    reviewer: "Jodan",
    rating: 4.5,
    body: "This controller is installed within my rack, powering a couple of Noctuas. Looks great, configurations and integration with Home Assistant were very easy to set up. Will most likely buy a couple more of these down the line. Would recommend.",
    displayQuote: "Looks great, configurations and integration with Home Assistant were very easy to set up.",
    source: "Tindie",
    datePublished: "2025-08-15",
    title: "Perfect for any Home Assistant Enthusiast!",
  },
  {
    reviewer: "Scott",
    rating: 4.5,
    body: "Used the fan controller to control fans within my server rack which badly needed some cooling and this works perfectly. Very well put together, would recommend.",
    displayQuote: "Used the fan controller to control fans within my server rack which badly needed some cooling. Works perfectly.",
    source: "Tindie",
    datePublished: "2025-07-13",
    title: "Exactly what I needed - very good product!",
  },
  {
    reviewer: "Marius",
    rating: 5,
    body: "I use it in a grow tent as fan controller, works perfect. Documentation is available on git.",
    displayQuote: "I use it in a grow tent as fan controller, works perfect. Documentation is available on git.",
    source: "Tindie",
    datePublished: "2025-03-01",
    title: "Perfect",
  },
];
