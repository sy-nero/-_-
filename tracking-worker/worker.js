/**
 * פיקסל מעקב הפתיחות — Cloudflare Worker.
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

export default {
  async fetch(request, env, ctx) {
    const path = new URL(request.url).pathname;
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
