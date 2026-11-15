/**
 * /trail-index.json: a compact index the book pages fetch on demand for the
 * "Reshuffle" and "Leap" controls. Rows are
 * [id, title, author, cover_url, [theme indexes], recommended].
 */
module.exports = {
  data() {
    return {
      permalink: "/trail-index.json",
      eleventyExcludeFromCollections: true,
    };
  },

  render({ catalog }) {
    const themes = catalog.themes.map((t) => t.slug);
    return JSON.stringify({
      themes,
      books: catalog.books.map((b) => [
        b.id,
        b.title,
        b.author || "",
        b.cover_url || null,
        (b.themes || []).map((s) => themes.indexOf(s)).filter((i) => i >= 0),
        b.is_recommended === true ? 1 : 0,
      ]),
    });
  },
};
