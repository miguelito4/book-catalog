/**
 * The trail: a record of the books visited this session, plus the two book-page
 * controls that need the whole catalog (Reshuffle, Leap).
 *
 * Everything here is an enhancement. The doors on a book page are rendered at
 * build time; this script only adds the trail strip and un-hides the controls.
 * Nothing leaves the browser: the trail lives in sessionStorage and is gone
 * when the tab closes.
 */
(function () {
  var KEY = "alib:trail";
  var MAX = 14;

  function load() {
    try {
      var v = JSON.parse(sessionStorage.getItem(KEY) || "[]");
      return Array.isArray(v) ? v : [];
    } catch (e) {
      return [];
    }
  }
  function save(trail) {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(trail));
    } catch (e) {
      /* Storage unavailable: the trail just doesn't persist. */
    }
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  var here = document.querySelector("[data-book-id]");
  var hereId = here ? Number(here.getAttribute("data-book-id")) : null;

  // Record this page.
  var trail = load();
  if (here) {
    var last = trail[trail.length - 1];
    if (!last || last.id !== hereId) {
      trail.push({
        id: hereId,
        t: here.getAttribute("data-book-title"),
        c: here.getAttribute("data-book-cover") || null,
      });
      trail = trail.slice(-MAX);
      save(trail);
    }
  }

  // Draw the strip.
  var strip = document.getElementById("trail");
  function draw() {
    if (!strip) return;
    var list = strip.querySelector("[data-trail-list]");
    var count = strip.querySelector("[data-trail-count]");
    list.textContent = "";
    // A trail of one, on that one book's own page, says nothing yet.
    if (!trail.length || (here && trail.length < 2)) {
      strip.hidden = true;
      return;
    }
    trail.forEach(function (b) {
      var li = el("li", "trail__item");
      var a = el("a", "trail__link" + (b.id === hereId ? " is-here" : ""));
      a.href = "/book/" + b.id + "/";
      if (b.id === hereId) a.setAttribute("aria-current", "page");
      var cover = el("span", "trail__cover");
      if (b.c) {
        var img = el("img");
        img.src = b.c;
        img.alt = "";
        img.loading = "lazy";
        cover.appendChild(img);
      }
      a.appendChild(cover);
      a.appendChild(el("span", null, b.t));
      li.appendChild(a);
      list.appendChild(li);
    });
    count.textContent = trail.length + (trail.length === 1 ? " book" : " books");
    strip.hidden = false;
  }
  draw();

  var reset = strip && strip.querySelector("[data-trail-reset]");
  if (reset) {
    reset.addEventListener("click", function () {
      trail = here ? trail.slice(-1) : [];
      save(trail);
      draw();
    });
  }

  if (!here) return;

  // Publisher blurbs run long and push the doors off the screen: cut a long
  // summary to a dozen lines, with a control to open it.
  var summary = document.querySelector(".book-detail__summary");
  if (summary) {
    summary.classList.add("is-clamped");
    if (summary.scrollHeight > summary.clientHeight + 4) {
      var more = el("button", "text-button", "Read on");
      more.type = "button";
      more.setAttribute("aria-expanded", "false");
      more.addEventListener("click", function () {
        var open = summary.classList.toggle("is-clamped") === false;
        more.textContent = open ? "Show less" : "Read on";
        more.setAttribute("aria-expanded", String(open));
      });
      summary.insertAdjacentElement("afterend", more);
    } else {
      summary.classList.remove("is-clamped");
    }
  }

  // Reshuffle and Leap need the catalog; fetch it once, on first use.
  var index = null;
  function getIndex() {
    if (!index) {
      index = fetch("/trail-index.json").then(function (r) {
        if (!r.ok) throw new Error("trail-index " + r.status);
        return r.json();
      });
      index.catch(function () {
        index = null;
      });
    }
    return index;
  }
  function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  document.querySelectorAll("[data-leap]").forEach(function (btn) {
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var onlyRec = btn.getAttribute("data-leap") === "recommended";
      getIndex().then(function (data) {
        var pool = data.books.filter(function (b) {
          return b[0] !== hereId && (!onlyRec || b[5]);
        });
        if (pool.length) window.location.href = "/book/" + pick(pool)[0] + "/";
      });
    });
  });

  var reshuffle = document.querySelector("[data-reshuffle]");
  var shelf = document.querySelector("[data-shelf]");
  if (reshuffle && shelf) {
    reshuffle.hidden = false;
    reshuffle.addEventListener("click", function () {
      var slug = shelf.getAttribute("data-shelf");
      var author = here.getAttribute("data-book-author");
      getIndex().then(function (data) {
        var t = data.themes.indexOf(slug);
        var pool = data.books.filter(function (b) {
          return b[0] !== hereId && b[4].indexOf(t) >= 0 && b[2].split(";")[0].trim() !== author;
        });
        shelf.textContent = "";
        for (var n = 0; n < 4 && pool.length; n++) {
          var b = pool.splice(Math.floor(Math.random() * pool.length), 1)[0];
          var li = el("li");
          var a = el("a", "door");
          a.href = "/book/" + b[0] + "/";
          var cover = el("span", "door__cover");
          if (b[3]) {
            var img = el("img");
            img.src = b[3];
            img.alt = "";
            img.loading = "lazy";
            cover.appendChild(img);
          }
          var text = el("span", "door__text");
          text.appendChild(el("span", "door__title", b[1]));
          text.appendChild(el("span", "door__sub", b[2]));
          a.appendChild(cover);
          a.appendChild(text);
          if (b[5]) {
            var star = el("span", "door__star", "★");
            star.title = "Recommended";
            a.appendChild(star);
          }
          li.appendChild(a);
          shelf.appendChild(li);
        }
      });
    });
  }
})();
