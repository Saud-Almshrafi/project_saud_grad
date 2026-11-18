/* مكوّن التقويم الهجري المنبثق — جافاسكربت عادي بلا مكتبات ولا إنترنت.
 *
 * لا يحتوي منطق تقويم: يقرأ من الخادم (#hijri-calendar-data) جدولاً محسوباً بـ hijri-converter (أم القرى):
 *   years["1447"] = [[عدد أيام الشهر, يوم الأسبوع لأوله 0=الأحد], ... 12 شهراً]
 * القيمة تُرسل في input مخفي بصيغة YYYY-MM-DD هجري، والتحقق النهائي في الخادم.
 * إن لم يعمل هذا الملف: تبقى الخانة للقراءة فقط وتبقى القيمة المخفية كما أرسلها الخادم (لا يُحفظ تاريخ خاطئ).
 */
(function () {
  "use strict";
  var dataEl = document.getElementById("hijri-calendar-data");
  if (!dataEl) return;
  var D;
  try { D = JSON.parse(dataEl.textContent); } catch (e) { return; }

  var MONTHS = D.months, MIN_Y = D.min;
  var WEEK = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"];
  var WEEK_SHORT = ["أحد", "اثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت"];
  var TODAY = parse(D.today);
  var MOBILE = window.matchMedia ? window.matchMedia("(max-width: 600px)") : { matches: false };
  var instances = [];

  // ------------------------------------------------------------ أدوات تاريخ (من الجدول فقط)
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function iso(p) { return p.y + "-" + pad(p.m) + "-" + pad(p.d); }
  function parse(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
  }
  function info(y, m) { var r = D.years[String(y)]; return r ? r[m - 1] : null; }   // [len, firstWeekday]
  function fmt(p) { return p.d + " " + MONTHS[p.m - 1] + " " + p.y + "هـ"; }
  function cmp(a, b) { return (a.y - b.y) || (a.m - b.m) || (a.d - b.d); }
  function valid(p) { var i = p && info(p.y, p.m); return !!(i && p.d >= 1 && p.d <= i[0]); }
  function shiftMonth(y, m, n) {
    m += n;
    while (m < 1) { m += 12; y--; }
    while (m > 12) { m -= 12; y++; }
    return { y: y, m: m };
  }
  function addDays(p, n) {
    var y = p.y, m = p.m, d = p.d + n, i, s;
    for (;;) {
      i = info(y, m);
      if (!i) return null;
      if (d < 1) { s = shiftMonth(y, m, -1); y = s.y; m = s.m; i = info(y, m); if (!i) return null; d += i[0]; continue; }
      if (d > i[0]) { d -= i[0]; s = shiftMonth(y, m, 1); y = s.y; m = s.m; continue; }
      return { y: y, m: m, d: d };
    }
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function btn(cls, text, act) {
    var b = el("button", cls, text);
    b.type = "button";
    if (act) b.setAttribute("data-act", act);
    return b;
  }

  // ------------------------------------------------------------------ المكوّن
  function Picker(root) {
    var self = this;
    this.root = root;
    this.hidden = root.querySelector("[data-value]");
    this.display = root.querySelector("[data-display]");
    this.optional = root.hasAttribute("data-optional");
    this.role = root.getAttribute("data-role") || "";
    this.pairId = root.getAttribute("data-pair") || "";
    this.pop = null;
    function toggle(e) { e.preventDefault(); if (self.pop) self.close(true); else self.open(); }
    this.display.addEventListener("click", toggle);
    root.querySelector("[data-open]").addEventListener("click", toggle);
    this.display.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") { e.preventDefault(); self.open(); }
      else if ((e.key === "Delete" || e.key === "Backspace") && self.optional) { e.preventDefault(); self.set(null); }
    });
    root.classList.add("hdp-ready");
  }

  // حدود الاختيار: لا شيء بعد اليوم، و«إلى» لا يسبق «من»، و«من» لا يتجاوز «إلى».
  Picker.prototype.partner = function () {
    var p = this.pairId && document.getElementById(this.pairId);
    return p ? parse(p.querySelector("[data-value]").value) : null;
  };
  Picker.prototype.minDate = function () {
    var lo = { y: MIN_Y, m: 1, d: 1 }, p = this.role === "to" ? this.partner() : null;
    return p && cmp(p, lo) > 0 ? p : lo;
  };
  Picker.prototype.maxDate = function () {
    var p = this.role === "from" ? this.partner() : null;
    return p && cmp(p, TODAY) < 0 ? p : TODAY;
  };
  Picker.prototype.allowed = function (p) {
    return valid(p) && cmp(p, this.minDate()) >= 0 && cmp(p, this.maxDate()) <= 0;
  };
  Picker.prototype.monthOpen = function (y, m) {  // هل في الشهر يوم واحد قابل للاختيار؟
    var i = info(y, m);
    return !!i && cmp({ y: y, m: m, d: i[0] }, this.minDate()) >= 0 && cmp({ y: y, m: m, d: 1 }, this.maxDate()) <= 0;
  };
  Picker.prototype.yearOpen = function (y) {
    for (var m = 1; m <= 12; m++) if (this.monthOpen(y, m)) return true;
    return false;
  };

  Picker.prototype.set = function (p) {
    this.hidden.value = p ? iso(p) : "";
    this.display.value = p ? fmt(p) : "";
    this.hidden.dispatchEvent(new Event("change", { bubbles: true }));
  };

  Picker.prototype.open = function () {
    var self = this;
    instances.forEach(function (o) { if (o !== self && o.pop) o.close(false); });
    var sel = parse(this.hidden.value), start = valid(sel) ? sel : TODAY;
    if (cmp(start, this.maxDate()) > 0) start = this.maxDate();
    if (cmp(start, this.minDate()) < 0) start = this.minDate();
    this.cursor = start;
    this.page = { y: start.y, m: start.m };
    this.view = "days";
    this.pop = el("div", "hdp-pop");
    this.pop.setAttribute("role", "dialog");
    this.pop.setAttribute("aria-label", "اختيار التاريخ الهجري");
    this.backdrop = el("div", "hdp-backdrop");
    document.body.appendChild(this.backdrop);
    this.root.appendChild(this.pop);
    this.display.setAttribute("aria-expanded", "true");
    this.pop.addEventListener("click", function (e) { self.onClick(e); });
    this.pop.addEventListener("keydown", function (e) { self.onKey(e); });
    this.outside = function (e) { if (!self.root.contains(e.target)) self.close(false); };
    document.addEventListener("mousedown", this.outside);
    document.addEventListener("touchstart", this.outside, { passive: true });
    this.render("cursor");
    this.place();
  };

  Picker.prototype.close = function (refocus) {
    if (!this.pop) return;
    document.removeEventListener("mousedown", this.outside);
    document.removeEventListener("touchstart", this.outside);
    this.pop.remove();
    this.backdrop.remove();
    this.pop = null;
    this.display.setAttribute("aria-expanded", "false");
    if (refocus) this.display.focus();
  };

  // على الشاشات الكبيرة: تحت الخانة دون الخروج عن حدود الشاشة. على الجوال: CSS يجعلها نافذة سفلية ثابتة.
  Picker.prototype.place = function () {
    var p = this.pop;
    p.classList.remove("hdp-up");
    p.style.right = "";
    if (MOBILE.matches) return;
    var r = p.getBoundingClientRect(), vw = document.documentElement.clientWidth;
    if (r.left < 8) p.style.right = (r.left - 8) + "px";
    else if (r.right > vw - 8) p.style.right = (r.right - (vw - 8)) + "px";
    if (r.bottom > window.innerHeight - 8 && r.top - r.height - this.display.offsetHeight > 8) p.classList.add("hdp-up");
  };

  Picker.prototype.render = function (focus) {
    var p = this.pop, self = this, pg = this.page;
    p.innerHTML = "";
    // الرأس: (RTL) السابق يميناً، العنوان، التالي يساراً
    var head = el("div", "hdp-head");
    var prev = btn("hdp-nav", "›", "prev"), next = btn("hdp-nav", "‹", "next");
    var title = el("div", "hdp-title");
    if (this.view === "days") {
      prev.setAttribute("aria-label", "الشهر السابق"); next.setAttribute("aria-label", "الشهر التالي");
      var pm = shiftMonth(pg.y, pg.m, -1), nm = shiftMonth(pg.y, pg.m, 1);
      prev.disabled = !this.monthOpen(pm.y, pm.m);
      next.disabled = !this.monthOpen(nm.y, nm.m);
      title.appendChild(btn("hdp-title-btn", MONTHS[pg.m - 1], "view-months"));
      title.appendChild(btn("hdp-title-btn", String(pg.y), "view-years"));
    } else if (this.view === "months") {
      prev.setAttribute("aria-label", "السنة السابقة"); next.setAttribute("aria-label", "السنة التالية");
      prev.disabled = !this.yearOpen(pg.y - 1);
      next.disabled = !this.yearOpen(pg.y + 1);
      title.appendChild(btn("hdp-title-btn", String(pg.y), "view-years"));
    } else {
      prev.disabled = next.disabled = true;
      prev.style.visibility = next.style.visibility = "hidden";
      title.appendChild(el("span", "hdp-title-text", "اختر السنة"));
    }
    head.appendChild(prev); head.appendChild(title); head.appendChild(next);
    p.appendChild(head);

    var body;
    if (this.view === "days") {
      body = el("div", "hdp-days");
      body.setAttribute("role", "grid");
      WEEK.forEach(function (w, i) {
        var h = el("div", "hdp-wd", WEEK_SHORT[i]);
        h.setAttribute("title", w); h.setAttribute("aria-label", w);
        body.appendChild(h);
      });
      var inf = info(pg.y, pg.m), sel = parse(this.hidden.value);
      for (var b = 0; b < inf[1]; b++) body.appendChild(el("span", "hdp-blank"));
      for (var d = 1; d <= inf[0]; d++) {
        var day = { y: pg.y, m: pg.m, d: d }, c = btn("hdp-day", String(d), "day");
        c.setAttribute("data-d", d);
        c.setAttribute("aria-label", fmt(day));
        c.tabIndex = -1;
        if (!cmp(day, TODAY)) { c.classList.add("is-today"); c.setAttribute("aria-current", "date"); }
        if (sel && !cmp(day, sel)) { c.classList.add("is-selected"); c.setAttribute("aria-selected", "true"); }
        if (!this.allowed(day)) { c.classList.add("is-disabled"); c.setAttribute("aria-disabled", "true"); }
        if (this.cursor && !cmp(day, this.cursor)) { c.classList.add("is-cursor"); c.tabIndex = 0; }
        body.appendChild(c);
      }
    } else if (this.view === "months") {
      body = el("div", "hdp-grid hdp-months");
      MONTHS.forEach(function (name, i) {
        var c = btn("hdp-cell", name, "month");
        c.setAttribute("data-m", i + 1);
        if (!self.monthOpen(pg.y, i + 1)) { c.classList.add("is-disabled"); c.setAttribute("aria-disabled", "true"); }
        if (i + 1 === pg.m) c.classList.add("is-cursor");
        if (pg.y === TODAY.y && i + 1 === TODAY.m) c.classList.add("is-today");
        body.appendChild(c);
      });
    } else {
      body = el("div", "hdp-grid hdp-years");
      for (var y = MIN_Y; y <= TODAY.y; y++) {
        var cy = btn("hdp-cell", String(y), "year");
        cy.setAttribute("data-y", y);
        if (!this.yearOpen(y)) { cy.classList.add("is-disabled"); cy.setAttribute("aria-disabled", "true"); }
        if (y === pg.y) cy.classList.add("is-cursor");
        if (y === TODAY.y) cy.classList.add("is-today");
        body.appendChild(cy);
      }
    }
    p.appendChild(body);

    var foot = el("div", "hdp-foot");
    var tb = btn("hdp-act", "اليوم", "today");
    if (!this.allowed(TODAY)) { tb.disabled = true; tb.title = "خارج النطاق المسموح"; }
    foot.appendChild(tb);
    if (this.optional) foot.appendChild(btn("hdp-act hdp-clear", "مسح", "clear"));
    foot.appendChild(btn("hdp-act hdp-close", "إغلاق", "close"));
    p.appendChild(foot);

    if (this.view === "years") {
      var cur = body.querySelector(".is-cursor");
      if (cur) body.scrollTop = cur.offsetTop - body.clientHeight / 2;
    }
    var target = focus && focus !== "cursor" ? p.querySelector('[data-act="' + focus + '"]:not(:disabled)') : null;
    (target || p.querySelector(".is-cursor") || p.querySelector("button:not(:disabled)")).focus();
  };

  Picker.prototype.onClick = function (e) {
    var b = e.target.closest("button");
    if (!b || b.disabled) return;
    var act = b.getAttribute("data-act"), pg = this.page, s;
    if (b.classList.contains("is-disabled")) return;
    if (act === "prev" || act === "next") {
      var n = act === "prev" ? -1 : 1;
      if (this.view === "days") { s = shiftMonth(pg.y, pg.m, n); this.page = s; }
      else this.page = { y: pg.y + n, m: pg.m };
      this.render(act);
    } else if (act === "view-months") { this.view = "months"; this.render("cursor"); }
    else if (act === "view-years") { this.view = "years"; this.render("cursor"); }
    else if (act === "month") {
      this.page = { y: pg.y, m: +b.getAttribute("data-m") };
      this.view = "days"; this.moveCursorIntoPage(); this.render("cursor");
    } else if (act === "year") {
      var y = +b.getAttribute("data-y"), m = pg.m;
      if (!this.monthOpen(y, m)) { for (m = 12; m >= 1 && !this.monthOpen(y, m); m--); }
      this.page = { y: y, m: m };
      this.view = "months"; this.render("cursor");
    } else if (act === "day") {
      this.set({ y: pg.y, m: pg.m, d: +b.getAttribute("data-d") });
      this.close(true);
    } else if (act === "today") { this.set(TODAY); this.close(true); }
    else if (act === "clear") { this.set(null); this.close(true); }
    else if (act === "close") { this.close(true); }
  };

  Picker.prototype.moveCursorIntoPage = function () {
    var i = info(this.page.y, this.page.m), d = Math.min(this.cursor ? this.cursor.d : 1, i[0]);
    this.cursor = { y: this.page.y, m: this.page.m, d: d };
  };

  // لوحة المفاتيح: (RTL) يسار = للأمام، يمين = للخلف؛ أعلى/أسفل = أسبوع؛ PageUp/PageDown = شهر؛ Enter يختار؛ Esc يغلق.
  Picker.prototype.onKey = function (e) {
    if (e.key === "Escape") { e.preventDefault(); this.close(true); return; }
    if ((e.key === "Enter" || e.key === " ") && e.target.tagName === "BUTTON") {
      e.preventDefault(); e.target.click(); return;     // Enter/مسافة = اختيار الزر المركَّز
    }
    var k = e.key, isDay = e.target.classList && e.target.classList.contains("hdp-day");
    if (this.view === "days" && isDay) {
      var step = { ArrowLeft: 1, ArrowRight: -1, ArrowDown: 7, ArrowUp: -7 }[k], np = null;
      if (step) np = addDays(this.cursor, step);
      else if (k === "PageDown" || k === "PageUp") {
        var s = shiftMonth(this.cursor.y, this.cursor.m, k === "PageDown" ? 1 : -1), i = info(s.y, s.m);
        np = i ? { y: s.y, m: s.m, d: Math.min(this.cursor.d, i[0]) } : null;
      } else if (k === "Home" || k === "End") {
        np = { y: this.cursor.y, m: this.cursor.m, d: k === "Home" ? 1 : info(this.cursor.y, this.cursor.m)[0] };
      } else return;
      e.preventDefault();
      if (!np) return;
      var lastOpen = info(TODAY.y, TODAY.m);
      if (cmp(np, { y: MIN_Y, m: 1, d: 1 }) < 0 || cmp(np, { y: TODAY.y, m: TODAY.m, d: lastOpen[0] }) > 0) return;
      this.cursor = np;
      this.page = { y: np.y, m: np.m };
      this.render("cursor");
      return;
    }
    // شبكتا الأشهر والسنوات: تنقّل بين الأزرار
    var grid = e.target.closest(".hdp-grid");
    if (!grid) return;
    var cols = this.view === "months" ? 3 : 4;
    var delta = { ArrowLeft: 1, ArrowRight: -1, ArrowDown: cols, ArrowUp: -cols }[k];
    if (!delta) return;
    e.preventDefault();
    var cells = Array.prototype.slice.call(grid.querySelectorAll("button"));
    var idx = cells.indexOf(e.target) + delta;
    if (idx >= 0 && idx < cells.length) cells[idx].focus();
  };

  function init() {
    document.querySelectorAll("[data-hdp]").forEach(function (root) {
      if (!root.classList.contains("hdp-ready")) instances.push(new Picker(root));
    });
  }
  window.addEventListener("resize", function () { instances.forEach(function (o) { if (o.pop) o.place(); }); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
  window.HijriPicker = { init: init, instances: instances };  // للاختبار
})();
