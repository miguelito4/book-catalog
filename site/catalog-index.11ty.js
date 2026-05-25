module.exports = {
  data() {
    return {
      permalink: "/catalog-index.json",
      eleventyExcludeFromCollections: true,
    };
  },

  render({ catalog }) {
    const output = {
      generated_at: catalog.generated_at,
      stats: catalog.stats,
      themes: catalog.themes.map(({ slug, name, book_count }) => ({
        slug,
        name,
        book_count,
      })),
      books: catalog.books.map((b) => ({
        id: b.id,
        isbn13: b.isbn13 ?? null,
        recommended: b.is_recommended === true,
      })),
    };
    return JSON.stringify(output);
  },
};
