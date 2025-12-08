/**
 * Eleventy configuration for the book catalog site.
 * 
 * This configures Eleventy to:
 * - Use Nunjucks templates
 * - Generate individual pages for each book
 * - Process the catalog.json data file
 * - Copy static assets
 */

module.exports = function(eleventyConfig) {
  
  // Copy static assets
  eleventyConfig.addPassthroughCopy("site/css");
  eleventyConfig.addPassthroughCopy("site/img");
  eleventyConfig.addPassthroughCopy("site/fonts");
  
  // Watch for changes in CSS
  eleventyConfig.addWatchTarget("site/css/");
  
  // Custom filter: format date
  eleventyConfig.addFilter("formatDate", (dateString) => {
    if (!dateString) return "";
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", { 
      year: "numeric", 
      month: "long"
    });
  });
  
  // Custom filter: format year
  eleventyConfig.addFilter("formatYear", (dateOrYear) => {
    if (!dateOrYear) return "";
    if (typeof dateOrYear === "number") return dateOrYear.toString();
    const date = new Date(dateOrYear);
    return date.getFullYear().toString();
  });
  
  // Custom filter: truncate text
  eleventyConfig.addFilter("truncate", (text, length = 200) => {
    if (!text) return "";
    if (text.length <= length) return text;
    return text.substring(0, length).trim() + "…";
  });
  
  // Custom filter: slugify for URLs
  eleventyConfig.addFilter("slugify", (text) => {
    if (!text) return "";
    return text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");
  });
  
  // Custom filter: get books by theme
  eleventyConfig.addFilter("byTheme", (books, themeSlug) => {
    if (!themeSlug || themeSlug === "all") return books;
    return books.filter(book => book.themes && book.themes.includes(themeSlug));
  });
  
  // Custom filter: get recommended books
  eleventyConfig.addFilter("recommended", (books) => {
    return books.filter(book => book.is_recommended);
  });
  
  // Custom filter: JSON stringify for Alpine.js
  eleventyConfig.addFilter("jsonify", (obj) => {
    return JSON.stringify(obj);
  });
  
  // Custom collection: create individual book pages
  eleventyConfig.addCollection("bookPages", function(collectionApi) {
    // Get the catalog data
    const catalog = require("./site/_data/catalog.json");
    
    // Return books as collection items with custom data
    return catalog.books.map(book => ({
      data: {
        ...book,
        layout: "book.njk",
        title: book.title,
        permalink: `/book/${book.id}/`,
      }
    }));
  });
  
  // Shortcode: book cover with fallback
  eleventyConfig.addShortcode("bookCover", function(book) {
    if (book.cover_url) {
      return `<img src="${book.cover_url}" alt="Cover of ${book.title}" class="book-cover" loading="lazy">`;
    }
    // Placeholder for books without covers
    return `<div class="book-cover book-cover--placeholder">
      <span class="book-cover__title">${book.title}</span>
      <span class="book-cover__author">${book.author || ""}</span>
    </div>`;
  });
  
  return {
    dir: {
      input: "site",
      output: "site/_site",
      includes: "_includes",
      data: "_data",
    },
    templateFormats: ["njk", "md", "html"],
    htmlTemplateEngine: "njk",
    markdownTemplateEngine: "njk",
  };
};
