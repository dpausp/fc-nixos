/*
 * Pure URL logic for the platform version switcher -- no DOM, no
 * fetch, only functions over (path, data). Loaded globally BEFORE
 * version-switcher.js (see zensical.toml extra_javascript) which
 * consumes this contract:
 *
 *   locate(path, data) -> {ver, entry, pageId, others} describing
 *     the page the reader is on, or null when the page-id is NOT a
 *     master page carried by at least one snapshot -- common pages
 *     get NO flyout (user decision 2026-08-18), the navigation tree
 *     stays undisplaced. ``others`` lists the carrying snapshot
 *     versions WITHOUT the master, in payload order.
 *
 *   targetHref(entry, here) -> the SAME page in the target version
 *     as a zensical .html URL (<entry.index><page-id>.html, one
 *     step, no version-index detour). Flyout rows only ever point
 *     at versions that carry the page -- the master by payload
 *     construction, snapshots per data.pages -- so this is pure URL
 *     arithmetic with no ?missing= case.
 *
 * URL spaces: "/" is the MASTER version's space (the local tree),
 * "/<ver>/" a checked-out snapshot's (make checkout-versioned-docs).
 * Page-ids are URL-shaped and match the generated data.pages keys in
 * window.PLATFORM_VERSIONS (make gen-platform-versions):
 * tree-relative paths sans .md with a trailing "index" component
 * folded away -- the root page has page-id "" and every href is
 * entry.index or entry.index + pageId + ".html". Directory URLs are
 * accepted on input for backwards compatibility.
 *
 * Data shape (generated, master-centric, keys deterministically
 * sorted):
 *
 *   window.PLATFORM_VERSIONS = {
 *     master: "<master ver>",
 *     versions: {"<ver>": {label, status, index}},
 *     pages: {"<page-id>": ["<ver>", ...]}  // master pages only
 *   };
 */
window.VersionSwitcherUrls = {
  PRIMARY_MOUNT_SELECTOR: ".md-sidebar--primary .md-sidebar__inner",
  SECONDARY_MOUNT_SELECTOR: ".md-sidebar--secondary .md-sidebar__inner",

  // The version entry whose URL space *path* lives in: the first path
  // segment naming a key of the versions map, else the MASTER entry
  // (the version serving "/"). Prototype-safe: the segment comes
  // from a URL.
  entryFor: function (path, data) {
    var seg = path.replace(/^\/+/, "").split("/")[0];
    if (seg && Object.prototype.hasOwnProperty.call(data.versions, seg)) {
      return data.versions[seg];
    }
    return data.versions[data.master] || null;
  },

  // path -> page-id relative to its version space ("" = manual root).
  // Handles both directory URLs ("/components/docker/") and .html URLs
  // ("/components/docker.html", "/components/docker/index.html", "/index.html").
  pageIdFor: function (path, entry) {
    var rest = entry && entry.index !== "/" ? path.slice(entry.index.length) : path;
    var pageId = rest.replace(/^\/+|\/+$/g, "");
    if (pageId.endsWith(".html")) {
      pageId = pageId.slice(0, -5);
      if (pageId.endsWith("/index")) {
        pageId = pageId.slice(0, -6);
      } else if (pageId === "index") {
        pageId = "";
      }
    }
    if (pageId.endsWith("/index")) {
      pageId = pageId.slice(0, -6);
    }
    return pageId;
  },

  // data.pages carriers for *pageId* -- the snapshot versions carrying
  // it, WITHOUT the master -- or [] when the master tree has no such
  // page (or no snapshot carries it). Prototype-safe: page-ids come
  // from URLs.
  carriersOf: function (pageId, data) {
    if (!Object.prototype.hasOwnProperty.call(data.pages, pageId)) {
      return [];
    }
    return data.pages[pageId];
  },

  locate: function (path, data) {
    var entry = this.entryFor(path, data);
    if (!entry) return null;
    var pageId = this.pageIdFor(path, entry);
    // Master pages with >= 1 snapshot carrier only: every data.pages
    // key is a master page by generator construction, so an empty
    // carrier list means a common page -- nothing to switch here.
    var others = this.carriersOf(pageId, data);
    if (others.length === 0) return null;
    // The reader's version key: the first path segment when it names
    // a version, else the master -- same rule entryFor() applies.
    var seg = path.replace(/^\/+/, "").split("/")[0];
    var ver =
      seg && Object.prototype.hasOwnProperty.call(data.versions, seg)
        ? seg
        : data.master;
    return { ver: ver, entry: entry, pageId: pageId, others: others };
  },

  // The same page in *entry* as a zensical .html URL:
  // <entry.index><page-id>.html (same page, one step; the root page
  // is just the version index). Rows are built only from versions
  // that carry the page, so there is no missing-page case here --
  // version-switcher-fallback.js still explains ?missing= URLs from
  // stale links of earlier payload shapes.
  targetHref: function (entry, here) {
    return here.pageId === ""
      ? entry.index
      : entry.index + here.pageId + ".html";
  },
};
