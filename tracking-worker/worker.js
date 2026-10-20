/**
 * מעקב פתיחות ולחיצות — Cloudflare Worker.
 *
 * /px/<מזהה>.gif       פיקסל שקוף: רושם שהמייל נפתח.
 * /c/<מזהה>/<קישור>    קישור במייל: רושם לחיצה ומפנה ליעד. כתובת היעד נשמרת
 *                      בטבלה tracked_links ולא בקישור עצמו, כדי שאי אפשר יהיה
 *                      להשתמש בשירות להפניה לאתרים אחרים.
 *
 * למה זה בנפרד מהאפליקציה: האפליקציה רצה על המחשב של מירי, אבל הנמען פותח
 * את המייל מתי שבא לו — גם כשהמחשב כבוי. הפיקסל הוא הדבר היחיד שחייב להיות
 * זמין תמיד, והוא זעיר: תמונה של 42 בתים ושורה אחת שנכתבת ל-D1. בדיוק מה
 * ש-Worker נועד לו — תמיד ער, בלי זמן התעוררות, ובחינם.
 *
 * הוא כותב לאותו D1 שהאפליקציה קוראת ממנו, ולכן המספרים בלוח מתעדכנים לבד.
 */

// GIF שקוף 1x1, אותם בתים שהאפליקציה מגישה
const PIXEL = Uint8Array.from(atob(
  "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
), c => c.charCodeAt(0));

const HEADERS = {
  "Content-Type": "image/gif",
  "Content-Length": String(PIXEL.length),
  // בלי זה שרת המטמון של Gmail יגיש את התמונה בעצמו ולא נדע על הפתיחה
  "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
  "Pragma": "no-cache",
};

/** טבלאות הלידים ב-D1. שם הקמפיין נכנס לשם הטבלה, ולכן מגלים אותן בזמן ריצה. */
async function leadTables(db) {
  const { results } = await db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'leads%'")
    .all();
  return (results || []).map(r => r.name);
}

/** רושם פתיחה. הפתיחה הראשונה נשמרת עם חותמת זמן; הבאות רק מגדילות מונה. */
async function markOpened(db, trackId) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);
  for (const table of await leadTables(db)) {
    const hit = await db
      .prepare(`SELECT place_id FROM ${table} WHERE track_id = ?`)
      .bind(trackId).first();
    if (!hit) continue;
    await db.prepare(
      `UPDATE ${table}
          SET opened_at  = COALESCE(NULLIF(opened_at, ''), ?),
              open_count = COALESCE(open_count, 0) + 1
        WHERE track_id = ?`
    ).bind(now, trackId).run();
    return true;
  }
  return false;
}

/** רושם לחיצה. מי שלחץ גם פתח, גם אם הפיקסל לא נטען אצלו. */
async function markClicked(db, trackId) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);
  for (const table of await leadTables(db)) {
    const hit = await db
      .prepare(`SELECT place_id FROM ${table} WHERE track_id = ?`)
      .bind(trackId).first();
    if (!hit) continue;
    await db.prepare(
      `UPDATE ${table}
          SET clicked_at  = COALESCE(NULLIF(clicked_at, ''), ?),
              click_count = COALESCE(click_count, 0) + 1,
              opened_at   = COALESCE(NULLIF(opened_at, ''), ?)
        WHERE track_id = ?`
    ).bind(now, now, trackId).run();
    return true;
  }
  return false;
}

async function clickResponse(request, env, ctx, trackId, linkId) {
  let url = "";
  try {
    const row = await env.DB
      .prepare("SELECT url FROM tracked_links WHERE id = ?").bind(linkId).first();
    url = (row && row.url) || "";
  } catch (err) {
    console.error("link_lookup", err);
  }
  if (!/^https?:\/\//.test(url)) {
    return new Response("הקישור לא נמצא", {
      status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
  // ההפניה יוצאת מיד, והרישום אחריה, כמו בפיקסל
  ctx.waitUntil(
    markClicked(env.DB, trackId).catch(err => console.error("mark_clicked", err))
  );
  return Response.redirect(url, 302);
}

export default {
  async fetch(request, env, ctx) {
    const path = new URL(request.url).pathname;
    // בדיקה של האפליקציה לפני שליחה: האם השירות הזה כבר יודע להפנות לחיצות
    if (path === "/c/ping") {
      return new Response("clicks-ok", { headers: { "Content-Type": "text/plain" } });
    }
    const click = path.match(/^\/c\/([A-Za-z0-9_-]{8,128})\/(\d{1,9})$/);
    if (click && env.DB) {
      return clickResponse(request, env, ctx, click[1], Number(click[2]));
    }
    const match = path.match(/^\/px\/([A-Za-z0-9_-]{8,128})\.gif$/);

    // התמונה חוזרת תמיד ומיד. הרישום נעשה אחריה (waitUntil) כדי ששום
    // תקלה או איטיות במסד לא ישבור את התצוגה של המייל אצל הנמען.
    if (match && env.DB) {
      ctx.waitUntil(
        markOpened(env.DB, match[1]).catch(err => console.error("mark_opened", err))
      );
    }
    return new Response(PIXEL, { headers: HEADERS });
  },
};
