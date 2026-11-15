/**
 * Trail data: the "doors" out of each book page, computed at build time so the
 * book pages work without JavaScript.
 *
 *   trail[book.id] = { before, after, author, sameAuthor[], theme, shelf[] }
 *
 * - before / after: the books finished immediately before and after this one.
 *   Only books with a real date_read take part; year_read alone is not an order.
 * - sameAuthor: up to five other books by the same (first-listed) author.
 * - shelf: four other books filed under this book's first theme. The pick is
 *   seeded by the book id, so it is stable from build to build; the page's
 *   "Reshuffle" control redraws it client-side from /trail-index.json.
 */
const catalog = require("./catalog.json");

const firstAuthor = (b) => (b.author || "").split(";")[0].trim();

const card = (b) => ({
  id: b.id,
  title: b.title,
  author: b.author,
  cover_url: b.cover_url || null,
  is_recommended: b.is_recommended === true,
  date_read: b.date_read || null,
});

module.exports = () => {
  const books = catalog.books;
  const themeName = Object.fromEntries(catalog.themes.map((t) => [t.slug, t.name]));

  const dated = books
    .filter((b) => b.date_read)
    .sort((a, b) => a.date_read.localeCompare(b.date_read) || a.id - b.id);
  const position = new Map(dated.map((b, i) => [b.id, i]));

  const byAuthor = new Map();
  const byTheme = new Map();
  for (const b of books) {
    const a = firstAuthor(b);
    if (a) byAuthor.set(a, [...(byAuthor.get(a) || []), b]);
    for (const slug of b.themes || []) byTheme.set(slug, [...(byTheme.get(slug) || []), b]);
  }

  const out = {};
  for (const b of books) {
    const i = position.get(b.id);
    const author = firstAuthor(b);
    const sameAuthor = (byAuthor.get(author) || []).filter((o) => o.id !== b.id).slice(0, 5);
    const skip = new Set([b.id, ...sameAuthor.map((o) => o.id)]);

    const slug = (b.themes || [])[0] || null;
    const pool = slug ? byTheme.get(slug).filter((o) => !skip.has(o.id)) : [];
    let seed = (b.id * 9301 + 49297) % 233280;
    const shelf = [];
    while (shelf.length < 4 && pool.length) {
      seed = (seed * 9301 + 49297) % 233280;
      shelf.push(pool.splice(Math.floor((seed / 233280) * pool.length), 1)[0]);
    }

    out[b.id] = {
      before: i > 0 ? card(dated[i - 1]) : null,
      after: i !== undefined && i < dated.length - 1 ? card(dated[i + 1]) : null,
      author,
      sameAuthor: sameAuthor.map(card),
      theme: slug ? { slug, name: themeName[slug] || slug } : null,
      shelf: shelf.map(card),
    };
  }
  return out;
};
