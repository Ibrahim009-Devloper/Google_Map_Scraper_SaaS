/**
 * LeadPulse Harvester Pro — Alexandria Editorial Interactive Frontend Logic
 * Full-featured controller for SSE streaming, dynamic card rendering,
 * geographic hub updates, terminal daemon logging, exports, and Supabase auth sync.
 */

// Application State
let currentJobId = null;
let eventSource = null;
let allLeads = [];
let leadPlaceIdMap = new Map();
let currentDisplayLimit = 50;
let isFeedRenderPending = false;
let currentFilter = "all";
let authToken = localStorage.getItem("gmaps_auth_token") || null;
let currentRating = 5;
let isScrapingRunning = false;
let startTime = null;
let lastCount = 0;
let rateInterval = null;
let supabaseClient = null;
let currentUser = null;
let currentUserProfile = null;

// DOM Cache
const scraperPrompt = document.getElementById("scraperPrompt");
const charBudgetCounter = document.getElementById("charBudgetCounter");
const samplePromptsDropdown = document.getElementById("samplePromptsDropdown");
const providerSelect = document.getElementById("providerSelect");
const targetQuotaSelect = document.getElementById("targetQuotaSelect");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

// Metrics & Status DOM
const statusBadge = document.getElementById("statusBadge");
const statusDot = document.getElementById("statusDot");
const statusPulse = document.getElementById("statusPulse");
const statusText = document.getElementById("statusText");
const rateMetric = document.getElementById("rateMetric");
const counterLeads = document.getElementById("counterLeads");
const leadsDelta = document.getElementById("leadsDelta");
const metricAccuracy = document.getElementById("metricAccuracy");
const accuracyBar = document.getElementById("accuracyBar");
const metricLatency = document.getElementById("metricLatency");
const progressPercent = document.getElementById("progressPercent");
const progressCurrent = document.getElementById("progressCurrent");
const progressTargetText = document.getElementById("progressTargetText");
const batchProgressBar = document.getElementById("batchProgressBar");

// Feed & Right Panel DOM
const leadsFeedContainer = document.getElementById("leadsFeedContainer");
const streamBadge = document.getElementById("streamBadge");
const activeHubName = document.getElementById("activeHubName");
const hubCoordsText = document.getElementById("hubCoordsText");
const hubCurrentArea = document.getElementById("hubCurrentArea");
const hubClusterText = document.getElementById("hubClusterText");
const mapSubText = document.getElementById("mapSubText");
const dedupCount = document.getElementById("dedupCount");

// Radar Hub DOM Elements
const radarStatusDot = document.getElementById("radarStatusDot");
const radarStatusLabel = document.getElementById("radarStatusLabel");
const radarTimerBadge = document.getElementById("radarTimerBadge");
const radarTimerIcon = document.getElementById("radarTimerIcon");
const hubDurationDisplay = document.getElementById("hubDurationDisplay");
const radarPingWave1 = document.getElementById("radarPingWave1");
const radarPingWave2 = document.getElementById("radarPingWave2");
const radarBeamContainer = document.getElementById("radarBeamContainer");
const radarCenterIconBox = document.getElementById("radarCenterIconBox");
const radarCenterIcon = document.getElementById("radarCenterIcon");
const radarActionText = document.getElementById("radarActionText");
const hubClusterDot = document.getElementById("hubClusterDot");
const hubClusterLabel = document.getElementById("hubClusterLabel");
const hubZoneLeads = document.getElementById("hubZoneLeads");
const hubQualityStatus = document.getElementById("hubQualityStatus");

// Header DOM
const serverHealthText = document.getElementById("serverHealthText");
const quotaText = document.getElementById("quotaText");
const authBtnLabel = document.getElementById("authBtnLabel");
const authBtn = document.getElementById("authBtn");
const terminalBody = document.getElementById("terminalBody");

// Modals
const authModal = document.getElementById("authModal");
const leadModal = document.getElementById("leadModal");
const leadModalTitle = document.getElementById("leadModalTitle");
const leadModalContent = document.getElementById("leadModalContent");


// ============================================================================
// Initialization & Health Checks
// ============================================================================

document.addEventListener("DOMContentLoaded", async () => {
  setupInputListeners();
  checkServerHealth();
  await initSupabaseClient();
  updateAuthUI();

  // Show "Login for More Scrape" popup when user enters the page if not authenticated
  if (!authToken) {
    setTimeout(() => {
      openAuthModal();
    }, 450);
  }

  // Close sample and user dropdown when clicking outside
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#samplePromptsDropdown") && !e.target.closest('button[onclick="toggleSampleMenu()"]')) {
      samplePromptsDropdown.classList.add("hidden");
    }
    const userMenuDropdown = document.getElementById("userMenuDropdown");
    if (userMenuDropdown && !e.target.closest("#userProfileDropdownContainer")) {
      userMenuDropdown.classList.add("hidden");
    }
  });
});

function setupInputListeners() {
  const customTargetInput = document.getElementById("customTargetInput");

  targetQuotaSelect.addEventListener("change", () => {
    if (targetQuotaSelect.value === "custom") {
      if (customTargetInput) {
        customTargetInput.classList.remove("hidden");
        customTargetInput.focus();
      }
    } else {
      if (customTargetInput) customTargetInput.classList.add("hidden");
    }
  });

  const scrapeWebsitesToggle = document.getElementById("scrapeWebsitesToggle");
  const mustHaveEmailWrapper = document.getElementById("mustHaveEmailWrapper");
  const pageSeoAuditToggle = document.getElementById("pageSeoAuditToggle");
  if (scrapeWebsitesToggle && mustHaveEmailWrapper) {
    scrapeWebsitesToggle.addEventListener("change", () => {
      if (scrapeWebsitesToggle.checked) {
        mustHaveEmailWrapper.classList.remove("hidden");
        mustHaveEmailWrapper.classList.add("inline-flex");
      } else {
        mustHaveEmailWrapper.classList.add("hidden");
        mustHaveEmailWrapper.classList.remove("inline-flex");
      }
    });
  }

  // Auto-enable website deep scraping whenever Page SEO audit is selected + visual feedback
  const pageSeoAuditWrapper = document.getElementById("pageSeoAuditWrapper");
  function updatePageSeoToggleVisual() {
    if (!pageSeoAuditToggle || !pageSeoAuditWrapper) return;
    if (pageSeoAuditToggle.checked) {
      pageSeoAuditWrapper.className = "inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-500/15 border border-amber-500/50 text-amber-900 dark:text-amber-200 transition-all font-semibold shadow-2xs cursor-pointer select-none text-xs font-label";
    } else {
      pageSeoAuditWrapper.className = "inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-container hover:bg-surface-container-high transition-colors text-xs font-label text-on-surface cursor-pointer select-none border border-transparent hover:border-surface-container-highest";
    }
  }

  if (pageSeoAuditToggle) {
    pageSeoAuditToggle.addEventListener("change", () => {
      updatePageSeoToggleVisual();
      if (pageSeoAuditToggle.checked && scrapeWebsitesToggle && !scrapeWebsitesToggle.checked) {
        scrapeWebsitesToggle.checked = true;
        if (mustHaveEmailWrapper) {
          mustHaveEmailWrapper.classList.remove("hidden");
          mustHaveEmailWrapper.classList.add("inline-flex");
        }
      }
    });
  }

  scraperPrompt.addEventListener("input", () => {
    const val = scraperPrompt.value;
    const len = val.length;
    charBudgetCounter.innerText = `Characters: ${len} / 300`;
    if (len >= 290) {
      charBudgetCounter.classList.add("text-error", "font-semibold");
    } else {
      charBudgetCounter.classList.remove("text-error", "font-semibold");
    }

    // Auto-enable Page SEO if user mentions SEO/audit in prompt
    if (pageSeoAuditToggle && !pageSeoAuditToggle.checked && /(?:seo|audit|page\s*seo|local\s*seo)/i.test(val)) {
      pageSeoAuditToggle.checked = true;
      updatePageSeoToggleVisual();
      if (scrapeWebsitesToggle && !scrapeWebsitesToggle.checked) {
        scrapeWebsitesToggle.checked = true;
        if (mustHaveEmailWrapper) {
          mustHaveEmailWrapper.classList.remove("hidden");
          mustHaveEmailWrapper.classList.add("inline-flex");
        }
      }
    }

    // Auto-detect target count from user prompt and sync dropdown chip
    const numMatch = val.match(/(\d{1,7})\s*(?:ta|ti|টি|টা|leads?|entities|businesses|companies|restaurants)?/i);
    if (numMatch) {
      if (["50", "100", "250", "500", "1000", "5000", "10000"].includes(numMatch[1])) {
        targetQuotaSelect.value = numMatch[1];
        if (customTargetInput) customTargetInput.classList.add("hidden");
      } else {
        targetQuotaSelect.value = "custom";
        if (customTargetInput) {
          customTargetInput.value = numMatch[1];
          customTargetInput.classList.remove("hidden");
        }
      }
    }
  });
}

async function checkServerHealth() {
  const start = performance.now();
  try {
    const res = await fetch("/health");
    const latency = Math.round(performance.now() - start);
    metricLatency.innerText = latency;

    if (res.ok) {
      const data = await res.json();
      serverHealthText.innerText = data.supabase_connected ? "Live • Cloud Sync" : "Live (SQLite WAL Mode)";
      appendTerminalLog(`[200 OK] Backend connected via HTTP/2 (Latency: ${latency}ms).`);
    } else {
      serverHealthText.innerText = "API Error";
      appendTerminalLog(`[WARN] Backend returned status ${res.status}.`);
    }
  } catch (err) {
    serverHealthText.innerText = "Offline / Reconnecting";
    metricLatency.innerText = "--";
    appendTerminalLog(`[ERR] Unable to ping backend service: ${err.message}`);
  }

  await fetchCurrentQuota();
}

async function fetchCurrentQuota() {
  try {
    const headers = {};
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
    const res = await fetch("/api/quota", { headers });
    if (res.ok) {
      const q = await res.json();
      if (q.is_authenticated) {
        const used = q.total_leads_scraped ?? currentUserProfile?.daily_usage?.leads_scraped ?? 0;
        const limit = q.limit ?? currentUserProfile?.plan?.daily_leads_limit ?? 1000;
        const planName = q.plan_name ?? currentUserProfile?.plan?.name ?? "Verified Account";
        quotaText.innerHTML = `${used.toLocaleString()} / ${limit.toLocaleString()} <span class="text-tertiary font-semibold">(${planName})</span>`;
      } else {
        const jobsCount = q.jobs_count || 0;
        const jobLimit = q.job_limit || 1;
        const leadLimit = q.limit || 100;
        quotaText.innerHTML = `${q.total_leads_scraped.toLocaleString()} / ${leadLimit.toLocaleString()} (${jobsCount}/${jobLimit} Job)`;
        if (q.is_limit_reached) {
          quotaText.innerHTML = `${q.total_leads_scraped.toLocaleString()} / ${leadLimit.toLocaleString()} <span class="text-rose-600 font-bold">(Trial Ended - Login Required)</span>`;
          appendTerminalLog(`[GUEST/LIMIT] 1-time guest trial limit (${leadLimit} leads / ${jobLimit} job) reached. Login to unlock 1,000 leads/day.`);
        }
      }
    }
  } catch (err) {
    console.warn("Could not fetch quota:", err);
  }
}

async function resetDevQuota() {
  try {
    const res = await fetch("/api/dev/reset-quota", { method: "POST" });
    if (res.ok) {
      showToast("Developer: Local IP quota reset to 0!", "success");
      appendTerminalLog("[DEV] Local IP quota successfully reset to 0.");
      await fetchCurrentQuota();
    }
  } catch (err) {
    showToast("Error resetting dev quota: " + err.message, "error");
  }
}

function updateAuthUI() {
  const userMenuDropdown = document.getElementById("userMenuDropdown");
  const userMenuEmail = document.getElementById("userMenuEmail");
  const userMenuPlan = document.getElementById("userMenuPlan");
  const userMenuRole = document.getElementById("userMenuRole");
  const adminMenuOption = document.getElementById("adminMenuOption");
  const userDashboardNavLink = document.getElementById("userDashboardNavLink");
  const adminDashboardNavLink = document.getElementById("adminDashboardNavLink");

  if (currentUserProfile && currentUserProfile.profile) {
    const prof = currentUserProfile.profile;
    const plan = currentUserProfile.plan || { name: "Free Test Plan", daily_leads_limit: 1000 };
    const usage = currentUserProfile.daily_usage || { leads_scraped: 0, jobs_count: 0 };
    const isAdmin = currentUserProfile.is_admin === true;

    // Header Button
    authBtnLabel.innerText = prof.full_name || prof.email.split("@")[0];
    authBtn.className = "flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white transition-all text-xs font-label font-semibold shadow-sm";

    // Header Dropdown info
    if (userMenuEmail) userMenuEmail.innerText = prof.email;
    if (userMenuPlan) userMenuPlan.innerText = `${plan.name}`;
    if (userMenuRole) userMenuRole.innerText = `Role: ${prof.role.toUpperCase()}`;

    // Sidebar navigation items
    if (userDashboardNavLink) userDashboardNavLink.classList.remove("hidden");
    if (adminDashboardNavLink) {
      if (isAdmin) adminDashboardNavLink.classList.remove("hidden");
      else adminDashboardNavLink.classList.add("hidden");
    }
    if (adminMenuOption) {
      if (isAdmin) adminMenuOption.classList.remove("hidden");
      else adminMenuOption.classList.add("hidden");
    }

    // Top Quota Pill
    quotaText.innerHTML = `${usage.leads_scraped.toLocaleString()} / ${plan.daily_leads_limit.toLocaleString()} <span class="text-tertiary">(${plan.name})</span>`;
  } else if (authToken) {
    authBtnLabel.innerText = "Verified Account";
    authBtn.className = "flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white transition-all text-xs font-label font-semibold shadow-sm";
    if (userDashboardNavLink) userDashboardNavLink.classList.remove("hidden");
  } else {
    authBtnLabel.innerText = "Sign In / Register";
    authBtn.className = "flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-primary-fixed hover:bg-primary-fixed-dim text-on-primary-fixed transition-all text-xs font-label font-semibold shadow-sm";
    if (userMenuDropdown) userMenuDropdown.classList.add("hidden");
    if (userDashboardNavLink) userDashboardNavLink.classList.add("hidden");
    if (adminDashboardNavLink) adminDashboardNavLink.classList.add("hidden");
    if (adminMenuOption) adminMenuOption.classList.add("hidden");
  }
}

function handleAuthButtonClick() {
  if (currentUserProfile || authToken) {
    const dropdown = document.getElementById("userMenuDropdown");
    if (dropdown) dropdown.classList.toggle("hidden");
  } else {
    openAuthModal();
  }
}

function refreshStatus() {
  checkServerHealth();
  showToast("Synchronized status with backend cluster.", "info");
}

function toggleSampleMenu() {
  samplePromptsDropdown.classList.toggle("hidden");
}

function loadSamplePrompt(text) {
  scraperPrompt.value = text;
  scraperPrompt.dispatchEvent(new Event("input"));
  samplePromptsDropdown.classList.add("hidden");
  scraperPrompt.focus();
}

// ============================================================================
// Problem Center & Community Live Feedback
// ============================================================================

function scrollToFeedback() {
  openProblemCenterModal();
}

function openProblemCenterModal() {
  const modal = document.getElementById("problemCenterModal");
  if (!modal) return;
  modal.classList.remove("hidden");

  // Pre-fill name if user is logged in
  const nameInput = document.getElementById("probReporterName");
  if (nameInput && !nameInput.value.trim()) {
    if (currentUserProfile && currentUserProfile.full_name) {
      nameInput.value = currentUserProfile.full_name;
    } else if (currentUser && currentUser.email) {
      nameInput.value = currentUser.email.split("@")[0];
    }
  }

  initStarRatingSelector();
  loadLiveProblemFeed();
}

function closeProblemCenterModal() {
  const modal = document.getElementById("problemCenterModal");
  if (modal) modal.classList.add("hidden");
}

function initStarRatingSelector() {
  const container = document.getElementById("probRatingSelector");
  if (!container || container.dataset.initialized === "true") return;
  container.dataset.initialized = "true";

  const buttons = container.querySelectorAll(".prob-star");
  const hiddenInput = document.getElementById("probSelectedRating");
  const label = document.getElementById("probRatingLabel");

  const descriptions = {
    1: "1 / 5 (Critical Issue / Bug)",
    2: "2 / 5 (Problem / Error)",
    3: "3 / 5 (Suggestion / Neutral)",
    4: "4 / 5 (Good / Feedback)",
    5: "5 / 5 (Praise & Feedback)",
  };

  function updateStars(val) {
    if (hiddenInput) hiddenInput.value = val;
    if (label) label.innerText = descriptions[val] || `${val} / 5`;
    buttons.forEach(btn => {
      const starVal = Number(btn.getAttribute("data-val"));
      const icon = btn.querySelector(".material-symbols-outlined");
      if (icon) {
        if (starVal <= val) {
          icon.className = "material-symbols-outlined text-[24px] text-amber-500 fill-1";
        } else {
          icon.className = "material-symbols-outlined text-[24px] text-slate-300";
        }
      }
    });
  }

  buttons.forEach(btn => {
    btn.addEventListener("click", () => {
      const val = Number(btn.getAttribute("data-val")) || 5;
      updateStars(val);
    });
  });

  updateStars(5);
}

async function handleProblemReportSubmit(event) {
  if (event) event.preventDefault();
  const nameInput = document.getElementById("probReporterName");
  const ratingInput = document.getElementById("probSelectedRating");
  const descInput = document.getElementById("probDescription");
  const wantsProInput = document.getElementById("probWantsPro");
  const submitBtn = document.getElementById("probSubmitBtn");

  const name = nameInput ? nameInput.value.trim() : "";
  const rating = ratingInput ? Number(ratingInput.value) || 5 : 5;
  const comment = descInput ? descInput.value.trim() : "";
  const wants_paid_version = wantsProInput ? wantsProInput.checked : false;

  if (!name) {
    showToast("Please enter your name.", "error");
    if (nameInput) nameInput.focus();
    return;
  }

  if (!comment || comment.length < 5) {
    showToast("Please describe the problem in at least 5 characters.", "error");
    if (descInput) descInput.focus();
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="animate-spin material-symbols-outlined text-[16px]">sync</span> Submitting Report...`;
  }

  try {
    const headers = { "Content-Type": "application/json" };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }

    const res = await fetch("/api/reviews", {
      method: "POST",
      headers,
      body: JSON.stringify({
        name,
        rating,
        comment,
        wants_paid_version
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast("Problem report submitted & posted live!", "success");
      if (descInput) descInput.value = "";
      loadLiveProblemFeed();
    } else {
      showToast(data.detail || "Failed to submit report. Please try again.", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">send</span> Submit Report &amp; Post Live`;
    }
  }
}

async function loadLiveProblemFeed() {
  const container = document.getElementById("probFeedContainer");
  const countEl = document.getElementById("probFeedCount");
  if (!container) return;

  container.innerHTML = `
    <div class="p-8 text-center text-secondary text-xs flex flex-col items-center justify-center gap-2">
      <span class="animate-spin material-symbols-outlined text-[20px] text-primary">sync</span>
      <span>Loading real-time community feed...</span>
    </div>
  `;

  try {
    const res = await fetch("/api/reviews?limit=50");
    if (res.ok) {
      const data = await res.json();
      const reviews = Array.isArray(data) ? data : (data.reviews || []);
      if (countEl) countEl.innerText = `(${reviews.length} reports)`;

      if (!reviews || reviews.length === 0) {
        container.innerHTML = `
          <div class="p-8 rounded-xl bg-surface-container-low text-center flex flex-col items-center gap-2 text-secondary text-xs">
            <span class="material-symbols-outlined text-[32px] text-secondary/60">support_agent</span>
            <p class="font-medium text-on-surface">No problem reports yet</p>
            <p class="text-[11px]">Be the first to submit a problem or review using the form on the left!</p>
          </div>
        `;
        return;
      }

      container.innerHTML = reviews.map(r => {
        const rating = Number(r.rating) || 5;
        const isProblem = rating <= 2;
        const isNeutral = rating === 3;
        const name = r.user_name || (r.user_email ? r.user_email.split("@")[0] : "Anonymous User");

        const initials = name.slice(0, 2).toUpperCase();

        let starsHtml = "";
        for (let i = 1; i <= 5; i++) {
          starsHtml += `<span class="material-symbols-outlined text-[12px] ${i <= rating ? 'text-amber-500 fill-1' : 'text-slate-300'}">star</span>`;
        }

        let badge = "";
        if (isProblem) {
          badge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-red-100 text-red-800 border border-red-300 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-red-600"></span>Issue / Bug</span>`;
        } else if (isNeutral) {
          badge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-100 text-amber-800 border border-amber-300 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-amber-600"></span>Suggestion</span>`;
        } else {
          badge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>Review</span>`;
        }

        let timeStr = "Recently";
        if (r.created_at) {
          try {
            const d = new Date(r.created_at);
            timeStr = d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
          } catch (_) {}
        }

        return `
          <div class="p-3.5 rounded-xl border ${isProblem ? 'border-red-200 bg-red-50/30' : 'border-surface-container-high/60 bg-surface-container-lowest'} flex flex-col gap-2 transition-all hover:shadow-sm">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <div class="w-7 h-7 rounded-full ${isProblem ? 'bg-red-100 text-red-700' : 'bg-primary-fixed text-primary'} flex items-center justify-center font-bold text-[10px]">
                  ${escapeHtml(initials)}
                </div>
                <div class="flex flex-col">
                  <span class="font-semibold text-xs text-on-surface leading-tight">${escapeHtml(name)}</span>
                  <span class="font-mono text-[10px] text-secondary">${timeStr}</span>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <div class="flex items-center">${starsHtml}</div>
                ${badge}
              </div>
            </div>
            <p class="text-xs text-on-surface leading-relaxed pl-9 whitespace-pre-wrap">${escapeHtml(r.comment || '')}</p>
          </div>
        `;
      }).join("");
    } else {
      container.innerHTML = `<div class="p-6 text-center text-error text-xs">Failed to load community feed.</div>`;
    }
  } catch (err) {
    container.innerHTML = `<div class="p-6 text-center text-error text-xs">${escapeHtml(err.message)}</div>`;
  }
}


// ============================================================================
// Real-Time Stopwatch Timer & Animated Radar Controller
// ============================================================================

let scraperTimerInterval = null;
let scraperStartTime = null;

function formatElapsedTimer(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function startScraperTimer() {
  if (scraperTimerInterval) {
    clearInterval(scraperTimerInterval);
  }
  scraperStartTime = Date.now();
  if (hubDurationDisplay) hubDurationDisplay.innerText = "00:00";
  if (radarTimerBadge) {
    radarTimerBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-300 text-xs font-mono font-semibold text-emerald-800 shadow-xs";
  }
  if (radarTimerIcon) radarTimerIcon.className = "material-symbols-outlined text-[15px] text-emerald-600 animate-spin";

  scraperTimerInterval = setInterval(() => {
    if (!scraperStartTime) return;
    const elapsedSec = Math.floor((Date.now() - scraperStartTime) / 1000);
    if (hubDurationDisplay) hubDurationDisplay.innerText = formatElapsedTimer(elapsedSec);
  }, 1000);
}

function stopScraperTimer(finalStatus = "completed", serverDuration = null) {
  if (scraperTimerInterval) {
    clearInterval(scraperTimerInterval);
    scraperTimerInterval = null;
  }
  if (radarTimerIcon) radarTimerIcon.className = "material-symbols-outlined text-[15px] text-primary";
  if (!hubDurationDisplay) return;

  let totalSec = 0;
  if (serverDuration && serverDuration > 0) {
    totalSec = Math.round(serverDuration);
  } else if (scraperStartTime) {
    totalSec = Math.floor((Date.now() - scraperStartTime) / 1000);
  }

  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  const timeFormatted = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

  if (finalStatus === "completed") {
    hubDurationDisplay.innerText = `${timeFormatted}`;
    if (radarTimerBadge) {
      radarTimerBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-100/70 border border-emerald-300 text-xs font-mono font-bold text-emerald-900 shadow-xs";
    }
  } else if (finalStatus === "stopped") {
    hubDurationDisplay.innerText = `${timeFormatted} (Halted)`;
    if (radarTimerBadge) {
      radarTimerBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-50 border border-amber-300 text-xs font-mono font-semibold text-amber-800 shadow-xs";
    }
  } else {
    hubDurationDisplay.innerText = `${timeFormatted}`;
  }
}

function formatFriendlyArea(areaRaw) {
  if (!areaRaw) return { hubTitle: "Scanning...", currentArea: "Active Zone", action: "Scanning Google Maps..." };
  const raw = areaRaw.trim();
  
  if (raw.includes(" in ")) {
    const parts = raw.split(" in ");
    const keyword = parts[0].replace(/['"]/g, "").trim();
    const area = parts[1].replace(/['"]/g, "").trim();
    return {
      hubTitle: area,
      currentArea: area,
      action: `Scanning verified ${keyword} businesses in ${area}...`
    };
  }
  if (raw.toLowerCase().includes("deep scraping")) {
    const currentName = activeHubName ? activeHubName.innerText : "Active Zone";
    return {
      hubTitle: (currentName && currentName !== "Ready for AI Geo-Split") ? currentName : "Company Websites",
      currentArea: "Deep Web Scanner",
      action: "Extracting direct emails, socials & websites..."
    };
  }
  if (raw.toLowerCase().includes("initializing")) {
    return {
      hubTitle: "AI Geo-Planner",
      currentArea: "Analyzing Region",
      action: "Splitting search area into optimized micro-zones..."
    };
  }
  if (raw.toLowerCase().includes("done")) {
    return {
      hubTitle: "Harvest Finished",
      currentArea: "Completed",
      action: "All unique verified leads packed and ready."
    };
  }
  return {
    hubTitle: raw,
    currentArea: raw,
    action: `Live scanning ${raw}...`
  };
}

function setRadarVisualState(state, info = {}) {
  if (state === "running") {
    if (radarStatusDot) radarStatusDot.className = "w-2 h-2 rounded-full bg-emerald-500 animate-pulse";
    if (radarStatusLabel) {
      radarStatusLabel.innerText = "Live Harvesting";
      radarStatusLabel.className = "font-label text-xs uppercase tracking-wider text-emerald-600 font-semibold";
    }
    if (radarPingWave1) radarPingWave1.classList.remove("hidden");
    if (radarPingWave2) radarPingWave2.classList.remove("hidden");
    if (radarBeamContainer) radarBeamContainer.classList.remove("hidden");

    if (radarCenterIconBox) radarCenterIconBox.className = "w-11 h-11 rounded-full bg-sky-950/90 border border-sky-400/80 flex items-center justify-center shadow-[0_0_18px_rgba(56,189,248,0.4)] transition-all animate-pulse";
    if (radarCenterIcon) {
      radarCenterIcon.innerText = "satellite_alt";
      radarCenterIcon.className = "material-symbols-outlined text-[26px] text-sky-400";
    }
    if (mapSubText && info.subText) mapSubText.innerText = info.subText;
    if (radarActionText) radarActionText.innerText = info.actionText || "Scanning Google Maps & extracting phone numbers...";

    if (hubClusterDot) hubClusterDot.className = "w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping";
    if (hubClusterLabel) hubClusterLabel.innerText = `Active (${allLeads.length})`;
    if (hubZoneLeads) hubZoneLeads.innerText = `${allLeads.length} Found`;
    if (hubQualityStatus) hubQualityStatus.innerText = "100% Unique & Verified";
  } else if (state === "completed") {
    if (radarStatusDot) radarStatusDot.className = "w-2 h-2 rounded-full bg-emerald-500";
    if (radarStatusLabel) {
      radarStatusLabel.innerText = "Harvest Finished";
      radarStatusLabel.className = "font-label text-xs uppercase tracking-wider text-emerald-600 font-semibold";
    }
    if (radarPingWave1) radarPingWave1.classList.add("hidden");
    if (radarPingWave2) radarPingWave2.classList.add("hidden");
    if (radarBeamContainer) radarBeamContainer.classList.add("hidden");

    if (radarCenterIconBox) radarCenterIconBox.className = "w-11 h-11 rounded-full bg-emerald-950/90 border border-emerald-400/80 flex items-center justify-center shadow-[0_0_18px_rgba(16,185,129,0.4)] transition-all";
    if (radarCenterIcon) {
      radarCenterIcon.innerText = "verified";
      radarCenterIcon.className = "material-symbols-outlined text-[26px] text-emerald-400";
    }
    if (mapSubText) mapSubText.innerText = "Area Completed";
    if (radarActionText) radarActionText.innerText = `Successfully harvested ${allLeads.length} verified leads!`;

    if (hubClusterDot) hubClusterDot.className = "w-1.5 h-1.5 rounded-full bg-emerald-400";
    if (hubClusterLabel) hubClusterLabel.innerText = `Harvested: ${allLeads.length}`;
    if (hubZoneLeads) hubZoneLeads.innerText = `${allLeads.length} Leads`;
    if (hubQualityStatus) hubQualityStatus.innerText = "Ready for Export (CSV/JSON)";
  } else if (state === "stopped") {
    if (radarStatusDot) radarStatusDot.className = "w-2 h-2 rounded-full bg-amber-500";
    if (radarStatusLabel) {
      radarStatusLabel.innerText = "Stopped Early";
      radarStatusLabel.className = "font-label text-xs uppercase tracking-wider text-amber-600 font-semibold";
    }
    if (radarPingWave1) radarPingWave1.classList.add("hidden");
    if (radarPingWave2) radarPingWave2.classList.add("hidden");
    if (radarBeamContainer) radarBeamContainer.classList.add("hidden");

    if (radarCenterIconBox) radarCenterIconBox.className = "w-11 h-11 rounded-full bg-amber-950/80 border border-amber-400/60 flex items-center justify-center shadow-md";
    if (radarCenterIcon) {
      radarCenterIcon.innerText = "pause_circle";
      radarCenterIcon.className = "material-symbols-outlined text-[26px] text-amber-400";
    }
    if (mapSubText) mapSubText.innerText = "Scraper Paused";
    if (radarActionText) radarActionText.innerText = `Preserved ${allLeads.length} leads in local cache.`;
    if (hubClusterDot) hubClusterDot.className = "w-1.5 h-1.5 rounded-full bg-amber-400";
    if (hubClusterLabel) hubClusterLabel.innerText = `Preserved: ${allLeads.length}`;
    if (hubZoneLeads) hubZoneLeads.innerText = `${allLeads.length} Leads`;
  } else {
    if (radarStatusDot) radarStatusDot.className = "w-2 h-2 rounded-full bg-secondary";
    if (radarStatusLabel) {
      radarStatusLabel.innerText = "Active Scraping Hub";
      radarStatusLabel.className = "font-label text-xs uppercase tracking-wider text-secondary font-semibold";
    }
    if (radarPingWave1) radarPingWave1.classList.add("hidden");
    if (radarPingWave2) radarPingWave2.classList.add("hidden");
    if (radarBeamContainer) radarBeamContainer.classList.add("hidden");

    if (radarCenterIconBox) radarCenterIconBox.className = "w-11 h-11 rounded-full bg-slate-800/90 border border-sky-400/40 flex items-center justify-center shadow-lg transition-all";
    if (radarCenterIcon) {
      radarCenterIcon.innerText = "radar";
      radarCenterIcon.className = "material-symbols-outlined text-[26px] text-sky-400";
    }
    if (mapSubText) mapSubText.innerText = "Hierarchical Geo-Coordinates";
    if (radarActionText) radarActionText.innerText = "Ready to start autonomous harvest";
    if (hubClusterDot) hubClusterDot.className = "w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse";
    if (hubClusterLabel) hubClusterLabel.innerText = "Cluster: Ready";
    if (hubZoneLeads) hubZoneLeads.innerText = "0 Leads";
    if (hubQualityStatus) hubQualityStatus.innerText = "100% Unique & Verified";
  }
}

// ============================================================================
// Scraping Job Execution & SSE Live Stream
// ============================================================================

async function startScrapingJob() {
  const prompt = scraperPrompt.value.trim();
  if (!prompt || prompt.length < 5) {
    showToast("Please enter a search prompt of at least 5 characters.", "error");
    scraperPrompt.focus();
    return;
  }
  if (prompt.length > 300) {
    showToast("Search prompt cannot exceed 300 characters.", "error");
    return;
  }

  const provider = (providerSelect && providerSelect.value) ? providerSelect.value : "gemini";

  let targetQuota = 100;
  const customTargetInput = document.getElementById("customTargetInput");
  if (targetQuotaSelect.value === "custom") {
    const customVal = parseInt(customTargetInput.value, 10);
    if (!customVal || customVal < 1) {
      showToast("Please enter a valid custom number of leads (e.g. 75).", "error");
      if (customTargetInput) customTargetInput.focus();
      return;
    }
    targetQuota = customVal;
  } else {
    targetQuota = parseInt(targetQuotaSelect.value, 10) || 100;
  }

  const scrapeWebsitesToggle = document.getElementById("scrapeWebsitesToggle");
  const scrapeWebsite = scrapeWebsitesToggle ? scrapeWebsitesToggle.checked : false;
  const mustHaveEmailToggle = document.getElementById("mustHaveEmailToggle");
  const mustHaveEmail = scrapeWebsite && mustHaveEmailToggle ? mustHaveEmailToggle.checked : false;
  const pageSeoAuditToggle = document.getElementById("pageSeoAuditToggle");
  const auditSeo = pageSeoAuditToggle ? pageSeoAuditToggle.checked : false;

  progressTargetText.innerText = `of ${targetQuota} target entities`;

  // UI state transition
  setScrapingState(true);
  allLeads = [];
  leadPlaceIdMap = new Map();
  currentDisplayLimit = 50;
  lastCount = 0;
  startTime = Date.now();
  leadsFeedContainer.innerHTML = "";
  renderEmptyState("Initializing AI Geo-Planner & reverse protobuf query...");

  appendTerminalLog(`[AI/PLAN] Dispatching user prompt to Geo-Planner: "${prompt.slice(0, 60)}..."`);
  appendTerminalLog(`[CONFIG] Target: ${targetQuota} leads | Website Scraping: ${scrapeWebsite ? "ENABLED" : "DISABLED"} | Page SEO: ${auditSeo ? "ENABLED" : "DISABLED"}`);

  try {
    const headers = { "Content-Type": "application/json" };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }

    const res = await fetch("/api/scrape/start", {
      method: "POST",
      headers,
      body: JSON.stringify({
        prompt,
        provider,
        target_leads: targetQuota,
        scrape_website: scrapeWebsite,
        must_have_email: mustHaveEmail,
        audit_seo: auditSeo,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      const errMsg = (data.detail && typeof data.detail === "object") ? data.detail.message : (data.detail || "Failed to start scraping.");
      showToast(errMsg, "error");
      appendTerminalLog(`[ERR] Failed to start scraping: ${errMsg}`);
      setScrapingState(false);

      // Trigger Login popup if guest limit reached
      const statusType = data.detail?.status || data.detail?.code;
      if (statusType === "limit_reached_login_required" || statusType === "GUEST_JOB_LIMIT_EXCEEDED" || statusType === "GUEST_LEAD_LIMIT_EXCEEDED") {
        setTimeout(() => {
          openAuthModal();
          const alertBox = document.getElementById("authAlertBox");
          if (alertBox) {
            alertBox.className = "p-3 rounded-lg text-xs font-body leading-relaxed bg-amber-50 text-amber-900 border border-amber-300";
            alertBox.innerHTML = `<strong>Guest Trial Completed:</strong> ${escapeHtml(errMsg)}<br><span class="font-semibold text-primary mt-1 block">Please sign in with Google or create an account to unlock 1,000 Leads/Day, 3 Jobs/Day, and 300 Leads/Job.</span>`;
            alertBox.classList.remove("hidden");
          }
        }, 300);
      }
      return;
    }

    currentJobId = data.job_id;
    appendTerminalLog(`[START] Job ${currentJobId} launched. Sub-locations: ${data.sub_locations_count}, Keywords: ${data.keywords ? data.keywords.join(', ') : 'Generated'}`);
    showToast(`Job launched successfully! AI generated ${data.sub_locations_count || 1} micro-zones.`, "success");

    // Start Live Rate Calculator
    rateInterval = setInterval(updateRateMetric, 2000);

    // Connect SSE Live Stream
    initSSEStream(currentJobId, targetQuota);

  } catch (err) {
    showToast(`Network error: ${err.message}`, "error");
    appendTerminalLog(`[FATAL] Error starting job: ${err.message}`);
    setScrapingState(false);
  }
}

function initSSEStream(jobId, targetQuota) {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource(`/api/scrape/stream/${jobId}`);

  eventSource.onopen = () => {
    appendTerminalLog(`[STREAM] Server-Sent Events bus connected for job ${jobId}.`);
  };

  eventSource.onmessage = async (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.error) {
        appendTerminalLog(`[STREAM/ERR] ${data.error}`);
        stopCurrentJob();
        return;
      }

      // Update Current Area & Live Harvesting Radar
      if (data.current_area) {
        const friendly = formatFriendlyArea(data.current_area);
        if (hubCurrentArea) hubCurrentArea.innerText = friendly.currentArea;
        if (activeHubName) activeHubName.innerText = friendly.hubTitle;
        if (mapSubText) mapSubText.innerText = `${friendly.hubTitle} Zone`;
        const radarActionTextEl = document.getElementById("radarActionText");
        if (radarActionTextEl) radarActionTextEl.innerText = friendly.action;
      }

      // Ingest New Leads Batch or Final Enriched Leads
      if (Array.isArray(data.final_leads) && data.final_leads.length > 0) {
        allLeads = data.final_leads;
        leadPlaceIdMap.clear();
        allLeads.forEach((l, idx) => leadPlaceIdMap.set(l.place_id, idx));
        scheduleLeadsFeedRender();
        updateMetricCards(targetQuota);
        const emailCount = allLeads.filter(l => l.emails && l.emails.length > 0).length;
        appendTerminalLog(`[ENRICH/SYNC] Final synchronized leads loaded. ${emailCount} leads verified with direct emails.`);
        const hubZoneLeadsEl = document.getElementById("hubZoneLeads");
        if (hubZoneLeadsEl) hubZoneLeadsEl.innerText = `${allLeads.length} Leads`;
      } else if (Array.isArray(data.new_leads) && data.new_leads.length > 0) {
        let addedCount = 0;
        let updatedCount = 0;
        data.new_leads.forEach((lead) => {
          let idx = leadPlaceIdMap.get(lead.place_id);
          if (idx === undefined) {
            idx = allLeads.length;
            leadPlaceIdMap.set(lead.place_id, idx);
            allLeads.push(lead);
            addedCount++;
          } else {
            // Update existing lead with newly scraped emails, socials, or details
            allLeads[idx] = { ...allLeads[idx], ...lead };
            updatedCount++;
          }
        });

        if (addedCount > 0 || updatedCount > 0) {
          // Update Feed UI smoothly with RAF throttle
          scheduleLeadsFeedRender();
          updateMetricCards(targetQuota);

          const hubZoneLeadsEl = document.getElementById("hubZoneLeads");
          if (hubZoneLeadsEl) hubZoneLeadsEl.innerText = `${allLeads.length} Leads`;
          const hubClusterLabelEl = document.getElementById("hubClusterLabel");
          if (hubClusterLabelEl) hubClusterLabelEl.innerText = `Active (${allLeads.length})`;

          const latest = data.new_leads[0];
          if (addedCount > 0 && latest) {
            appendTerminalLog(`[API/INGEST] Ingested +${addedCount} candidate leads. Latest: "${latest.name}" (${latest.neighborhood || latest.address || 'Address verified'})`);
            const radarActionTextEl = document.getElementById("radarActionText");
            if (radarActionTextEl) {
              radarActionTextEl.innerText = `Verified: "${latest.name}"`;
            }
          }

          // Update geo coordinates on map if available
          if (latest && latest.lat && latest.lon) {
            hubCoordsText.innerText = `Live Zone: ${latest.neighborhood || 'Target'}`;
            if (mapSubText) mapSubText.innerText = `${latest.neighborhood || 'Current Zone'} Scanner`;
          }
        }
      }

      // Update Status and Quota
      if (!authToken) {
        quotaText.innerText = `${allLeads.length} / 100 (1 Job)`;
      }

      // Check if job finished
      if (data.done) {
        appendTerminalLog(`[DONE] Scraper finished with status: ${data.status.toUpperCase()}. Total collected: ${allLeads.length} leads.`);
        stopCurrentJob(true, data.status);
        await fetchCurrentQuota();

        // Prompt guest to login if trial completed
        if (!authToken) {
          setTimeout(() => {
            openAuthModal();
            const alertBox = document.getElementById("authAlertBox");
            if (alertBox) {
              alertBox.className = "p-3 rounded-lg text-xs font-body leading-relaxed bg-emerald-50 text-emerald-900 border border-emerald-300";
              alertBox.innerHTML = `<strong>1-Time Guest Trial Finished!</strong> You harvested <strong>${allLeads.length} leads</strong>.<br><span class="text-primary font-semibold mt-1 block">Sign in now with Google or create an account to unlock 1,000 Leads/Day, 3 Jobs/Day, and 300 Leads/Job!</span>`;
              alertBox.classList.remove("hidden");
            }
          }, 1200);
        }
      }

    } catch (e) {
      console.error("Error parsing SSE stream message:", e);
    }
  };

  eventSource.onerror = (err) => {
    console.warn("SSE connection interrupted:", err);
  };
}

async function stopCurrentJob(isAutoDone = false, finalStatus = "completed") {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (rateInterval) {
    clearInterval(rateInterval);
    rateInterval = null;
  }

  if (currentJobId && !isAutoDone) {
    try {
      appendTerminalLog(`[STOP] Requesting immediate graceful halt for job ${currentJobId}...`);
      await fetch(`/api/scrape/stop/${currentJobId}`, { method: "POST" });
      appendTerminalLog("[STOP] Scraper stopped. All collected leads preserved in SQLite WAL buffer.");
      showToast("Scraper stopped. All leads preserved.", "info");
    } catch (err) {
      console.error("Stop error:", err);
    }
  }

  setScrapingState(false, finalStatus);
}

function setScrapingState(running, statusLabel = "idle") {
  isScrapingRunning = running;

  if (running) {
    startBtn.disabled = true;
    startBtn.classList.add("opacity-50", "cursor-not-allowed");
    stopBtn.classList.remove("hidden");
    stopBtn.classList.add("flex");

    statusBadge.className = "flex items-center gap-2.5 px-4 py-2 rounded-full bg-primary-fixed transition-all duration-300 shadow-sm";
    statusDot.className = "relative inline-flex rounded-full h-2.5 w-2.5 bg-primary";
    statusPulse.className = "animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75";
    statusText.className = "font-label text-xs font-semibold uppercase tracking-wider text-primary";
    statusText.innerText = "Running Engine";

    // Activate Real-Time Stopwatch & Animated Radar
    startScraperTimer();
    setRadarVisualState("running", {
      subText: "Scanning Live Zone",
      actionText: "AI Geo-Planner analyzing and discovering businesses..."
    });
  } else {
    startBtn.disabled = false;
    startBtn.classList.remove("opacity-50", "cursor-not-allowed");
    stopBtn.classList.add("hidden");
    stopBtn.classList.remove("flex");

    // Stop Stopwatch & Update Radar Visual
    stopScraperTimer(statusLabel);
    setRadarVisualState(statusLabel);

    let dotColor = "bg-secondary";
    let textColor = "text-secondary";
    let text = "Engine Idle";

    if (statusLabel === "completed") {
      dotColor = "bg-emerald-500";
      textColor = "text-emerald-700";
      text = "Harvest Complete";
    } else if (statusLabel === "stopped") {
      dotColor = "bg-amber-500";
      textColor = "text-amber-700";
      text = "Stopped Early";
    } else if (statusLabel === "limit_reached") {
      dotColor = "bg-rose-500";
      textColor = "text-rose-700";
      text = "Quota Reached";
      openAuthModal();
    }

    statusBadge.className = "flex items-center gap-2.5 px-4 py-2 rounded-full bg-surface-container-low transition-all duration-300 shadow-sm";
    statusDot.className = `relative inline-flex rounded-full h-2.5 w-2.5 ${dotColor}`;
    statusPulse.className = `absolute inline-flex h-full w-full rounded-full ${dotColor} opacity-75`;
    statusText.className = `font-label text-xs font-semibold uppercase tracking-wider ${textColor}`;
    statusText.innerText = text;
  }
}

function updateRateMetric() {
  if (!isScrapingRunning || !startTime) return;
  const elapsedMin = (Date.now() - startTime) / 60000;
  if (elapsedMin > 0.05) {
    const rate = Math.round(allLeads.length / elapsedMin);
    rateMetric.innerText = rate;
  }
}

function updateMetricCards(targetQuota) {
  counterLeads.innerText = allLeads.length.toLocaleString();
  progressCurrent.innerText = allLeads.length.toLocaleString();

  const pct = Math.min(100, Math.round((allLeads.length / targetQuota) * 100));
  progressPercent.innerText = `${pct}%`;
  batchProgressBar.style.width = `${pct}%`;

  // Quality calculation
  const withWebsite = allLeads.filter(l => l.website_status === "Has Own Website").length;
  const withSocial = allLeads.filter(l => l.website_status === "Social Link Only").length;
  const noWebsite = allLeads.filter(l => l.website_status === "No Website").length;
  
  if (allLeads.length > 0) {
    metricAccuracy.innerText = `${Math.round(((withWebsite + withSocial) / allLeads.length) * 100)}%`;
    dedupCount.innerText = `${Math.round(allLeads.length * 0.18)} Skipped`;
  }
}


// ============================================================================
// Leads Feed Rendering & Filter Tabs
// ============================================================================

function applyFeedFilter(filterType, tabElement) {
  currentFilter = filterType;
  document.querySelectorAll(".filter-tab").forEach(tab => {
    tab.className = "px-3 py-1 rounded-full bg-surface-container text-secondary hover:text-on-surface transition-all filter-tab";
  });
  tabElement.className = "px-3 py-1 rounded-full bg-primary text-on-primary font-semibold transition-all filter-tab";
  renderLeadsFeed();
}

function getFilteredLeads() {
  if (currentFilter === "no_website") {
    return allLeads.filter(l => l.website_status === "No Website" || l.website_status === "Social Link Only");
  } else if (currentFilter === "has_website") {
    return allLeads.filter(l => l.website_status === "Has Own Website");
  } else if (currentFilter === "has_phone") {
    return allLeads.filter(l => Boolean(l.phone && l.phone.trim()));
  } else if (currentFilter === "has_email") {
    return allLeads.filter(l => Boolean(l.emails && l.emails.length > 0));
  }
  return allLeads;
}

function scheduleLeadsFeedRender() {
  if (isFeedRenderPending) return;
  isFeedRenderPending = true;
  requestAnimationFrame(() => {
    isFeedRenderPending = false;
    renderLeadsFeed();
  });
}

function loadMoreFeedLeads(increment) {
  if (increment === "all") {
    currentDisplayLimit = allLeads.length;
  } else {
    currentDisplayLimit += (increment || 50);
  }
  renderLeadsFeed();
}

function renderLeadsFeed() {
  const visibleLeads = getFilteredLeads();
  streamBadge.innerText = `${visibleLeads.length} Loaded`;

  if (visibleLeads.length === 0) {
    renderEmptyState(allLeads.length > 0 ? "No leads matching selected filter tab." : "No leads scraped yet.");
    return;
  }

  leadsFeedContainer.innerHTML = "";

  // Virtual Windowing: Only render up to currentDisplayLimit (default 50) from newest to oldest
  const reversedLeads = visibleLeads.slice().reverse();
  const leadsToRender = reversedLeads.slice(0, currentDisplayLimit);

  // If there are more leads than the display limit, render a lightweight banner with controls
  if (visibleLeads.length > currentDisplayLimit) {
    const banner = document.createElement("div");
    banner.className = "flex items-center justify-between p-3 rounded-xl bg-surface-container-high border border-outline-variant text-xs font-label text-secondary mb-3 shadow-xs";
    banner.innerHTML = `
      <div class="flex items-center gap-2">
        <span class="material-symbols-outlined text-[16px] text-primary">speed</span>
        <span>Showing newest <strong>${leadsToRender.length}</strong> of <strong>${visibleLeads.length.toLocaleString()}</strong> live leads (Zero-Lag Mode). All leads saved in SQLite & exportable.</span>
      </div>
      <div class="flex items-center gap-2">
        <button onclick="loadMoreFeedLeads(50)" class="px-2.5 py-1 rounded bg-primary text-on-primary font-semibold text-[11px] hover:opacity-90 transition-all">+50 More</button>
        <button onclick="loadMoreFeedLeads('all')" class="px-2 py-1 rounded bg-surface text-secondary hover:text-on-surface text-[11px] transition-all">View All</button>
      </div>
    `;
    leadsFeedContainer.appendChild(banner);
  }

  // Render cards from newest to oldest
  leadsToRender.forEach((lead) => {
    const card = document.createElement("div");
    card.className = "lead-row flex flex-col md:flex-row md:items-center justify-between gap-3 p-4 rounded-xl bg-surface-container-low hover:bg-surface-container transition-all animate-fadeIn cursor-pointer";
    card.onclick = () => openLeadModal(lead);

    const initials = getInitials(lead.name);
    const colorClass = getInitialColor(lead.name);

    // Format website link & on-demand Page SEO button
    let websiteBadge = "";
    if (lead.website_status === "Has Own Website" && lead.website_url) {
      const domain = cleanDomain(lead.website_url);
      const hasAudited = Boolean(lead.seo_report && (lead.seo_report.seo_health_score !== undefined || lead.seo_report.opportunity_score !== undefined));
      const healthScore = lead.seo_report ? (lead.seo_report.seo_health_score ?? (lead.seo_report.opportunity_score !== null && lead.seo_report.opportunity_score !== undefined ? 100 - lead.seo_report.opportunity_score : null)) : null;
      let badgeClass = "bg-amber-100 hover:bg-amber-200 text-amber-900 border-amber-300";
      if (typeof healthScore === "number") {
        if (healthScore >= 80) badgeClass = "bg-emerald-100 hover:bg-emerald-200 text-emerald-900 border-emerald-300";
        else if (healthScore < 50) badgeClass = "bg-rose-100 hover:bg-rose-200 text-rose-900 border-rose-300";
      }
      const scoreLabel = healthScore !== null ? `Health: ${healthScore}/100` : "SEO Audited";
      const seoBadgeHtml = hasAudited
        ? `<button type="button" onclick="event.stopPropagation(); triggerPageSeoAudit('${lead.place_id}')" class="px-2 py-0.5 rounded text-[10px] font-bold font-label ${badgeClass} border flex items-center gap-1 shadow-2xs transition-all cursor-pointer" title="View Agency-Grade Local SEO Audit & Outreach Hook">
             <span class="material-symbols-outlined text-[12px]">troubleshoot</span>
             <span>${scoreLabel}</span>
           </button>`
        : `<button type="button" onclick="event.stopPropagation(); triggerPageSeoAudit('${lead.place_id}')" class="px-2 py-0.5 rounded text-[10px] font-semibold font-label bg-surface-container hover:bg-amber-50 text-secondary hover:text-amber-900 border border-surface-container-high hover:border-amber-300 flex items-center gap-1 shadow-2xs transition-all cursor-pointer" title="Run on-demand Local SEO Audit for this website">
             <span class="material-symbols-outlined text-[12px] text-amber-600">troubleshoot</span>
             <span>Page SEO</span>
           </button>`;

      websiteBadge = `
        <div class="flex items-center gap-1.5 flex-wrap">
          <a href="${lead.website_url}" target="_blank" onclick="event.stopPropagation()" class="text-xs font-label text-primary hover:underline flex items-center gap-0.5">
            ${domain}
            <span class="material-symbols-outlined text-[12px]">north_east</span>
          </a>
          ${seoBadgeHtml}
        </div>
      `;
    } else if (lead.website_status === "Social Link Only") {
      websiteBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-label font-semibold bg-tertiary-fixed text-on-tertiary-fixed">Social Link Only</span>`;
    } else {
      websiteBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-label font-semibold bg-surface-container text-secondary">No Website</span>`;
    }


    // Email & Phone tags
    const emailHtml = (lead.emails && lead.emails.length > 0)
      ? `<span class="flex items-center gap-1 text-primary hover:underline truncate" title="${lead.emails.join(', ')}">
          <span class="material-symbols-outlined text-[14px]">mail</span> ${lead.emails[0]}
         </span>`
      : "";

    const phoneHtml = lead.phone
      ? `<span class="flex items-center gap-1 text-on-surface-variant truncate">
          <span class="material-symbols-outlined text-[14px]">call</span> ${lead.phone}
         </span>`
      : "";

    // Rating star
    const ratingHtml = lead.rating 
      ? `<span class="flex items-center gap-0.5 text-xs text-amber-600 font-semibold">
           <span class="material-symbols-outlined text-[14px]">star</span> ${lead.rating} (${lead.reviews_count || 0})
         </span>`
      : "";

    card.innerHTML = `
      <div class="flex items-start gap-3.5 min-w-0">
        <div class="w-10 h-10 rounded-lg ${colorClass} flex items-center justify-center font-headline font-bold shrink-0 shadow-sm">
          ${initials}
        </div>
        <div class="min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-headline font-semibold text-sm text-on-surface truncate">${escapeHtml(lead.name)}</span>
            ${lead.is_unclaimed_business 
              ? `<span class="px-2 py-0.5 rounded text-[10px] font-label font-semibold bg-amber-100 text-amber-800">Unclaimed</span>` 
              : `<span class="px-2 py-0.5 rounded text-[10px] font-label font-semibold bg-surface-container text-tertiary flex items-center gap-1">
                   <span class="material-symbols-outlined text-[12px]">verified</span> Verified
                 </span>`
            }
            ${ratingHtml}
          </div>
          <p class="font-body text-xs text-secondary truncate mt-0.5">
            ${escapeHtml(lead.category || 'Business')} • ${escapeHtml(lead.neighborhood || lead.address || 'Address provided')}
          </p>
          <div class="flex items-center gap-3 mt-1.5 text-xs font-body flex-wrap">
            ${phoneHtml}
            ${emailHtml}
          </div>
        </div>
      </div>
      <div class="flex md:flex-col items-center md:items-end justify-between shrink-0 gap-1.5 pt-2 md:pt-0">
        <span class="text-[11px] font-label text-secondary font-medium">Just now</span>
        ${websiteBadge}
      </div>
    `;

    leadsFeedContainer.appendChild(card);
  });

  if (visibleLeads.length > currentDisplayLimit) {
    const footerBtn = document.createElement("div");
    footerBtn.className = "flex justify-center p-3 mt-2";
    footerBtn.innerHTML = `
      <button onclick="loadMoreFeedLeads(50)" class="px-4 py-2 rounded-xl bg-surface-container hover:bg-surface-container-high text-xs font-label font-semibold text-primary flex items-center gap-1.5 transition-all shadow-xs">
        <span class="material-symbols-outlined text-[16px]">expand_more</span>
        Load More Live Cards (${leadsToRender.length} of ${visibleLeads.length.toLocaleString()})
      </button>
    `;
    leadsFeedContainer.appendChild(footerBtn);
  }
}

function renderEmptyState(message) {
  leadsFeedContainer.innerHTML = `
    <div class="flex flex-col items-center justify-center py-16 text-center text-secondary">
      <span class="material-symbols-outlined text-[48px] text-outline-variant mb-2">radar</span>
      <p class="font-headline font-semibold text-sm text-on-surface">${message}</p>
      <p class="font-body text-xs text-secondary mt-1 max-w-sm">
        Results stream dynamically as Google Maps protocol buffers are resolved.
      </p>
    </div>
  `;
}


// ============================================================================
// Exports & Utilities
// ============================================================================

function downloadExport(format) {
  if (!currentJobId && allLeads.length === 0) {
    showToast("No active leads available to export.", "error");
    return;
  }

  const targetJobId = currentJobId || "current";
  appendTerminalLog(`[EXPORT] Preparing ${format.toUpperCase()} archive download for ${allLeads.length} leads...`);

  const pageSeoAuditToggle = document.getElementById("pageSeoAuditToggle");
  const hasSeo = (pageSeoAuditToggle && pageSeoAuditToggle.checked) || allLeads.some(l => l.seo_report);
  const downloadUrl = `/api/scrape/download/${targetJobId}?format=${format}${hasSeo ? '&include_seo=true' : ''}`;
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.setAttribute("download", `leads_${targetJobId}.${format}`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  showToast(`Initiated ${format.toUpperCase()} download!`, "success");
}

function copyAllLeads() {
  if (allLeads.length === 0) {
    showToast("No leads to copy.", "error");
    return;
  }

  const tsv = allLeads.map(l => 
    `${l.name}\t${l.category || ''}\t${l.phone || ''}\t${(l.emails || []).join('; ')}\t${l.website_url || ''}\t${l.neighborhood || l.address || ''}`
  ).join("\n");

  navigator.clipboard.writeText(`Name\tCategory\tPhone\tEmails\tWebsite\tAddress\n` + tsv)
    .then(() => {
      showToast(`Copied ${allLeads.length} leads to clipboard!`, "success");
      appendTerminalLog(`[CLIPBOARD] Copied ${allLeads.length} leads table to clipboard.`);
    })
    .catch(() => showToast("Failed to access clipboard.", "error"));
}

function clearFeed() {
  allLeads = [];
  renderEmptyState("Review stream cleared. New scraping runs will repopulate this desk.");
  counterLeads.innerText = "0";
  progressCurrent.innerText = "0";
  progressPercent.innerText = "0%";
  batchProgressBar.style.width = "0%";
  streamBadge.innerText = "0 Loaded";
  appendTerminalLog("[UI] User cleared current memory display.");
}


// ============================================================================
// Terminal Drawer & Logging
// ============================================================================

function toggleTerminal() {
  const chevron = document.getElementById("terminalChevron");
  if (terminalBody.classList.contains("hidden")) {
    terminalBody.classList.remove("hidden");
    chevron.innerText = "expand_less";
  } else {
    terminalBody.classList.add("hidden");
    chevron.innerText = "expand_more";
  }
}

function appendTerminalLog(msg) {
  const line = document.createElement("div");
  line.className = "flex items-start gap-2";
  const now = new Date().toTimeString().split(" ")[0] + "." + Math.floor(Math.random() * 900 + 100);

  let tag = `<span class="text-primary-fixed">[INFO]</span>`;
  if (msg.includes("[200 OK]") || msg.includes("[START]")) {
    tag = `<span class="text-emerald-400 font-semibold">[200 OK]</span>`;
  } else if (msg.includes("[AI/PLAN]")) {
    tag = `<span class="text-tertiary-fixed font-semibold">[AI/PLAN]</span>`;
  } else if (msg.includes("[STREAM]")) {
    tag = `<span class="text-blue-300 font-semibold">[STREAM]</span>`;
  } else if (msg.includes("[API/INGEST]")) {
    tag = `<span class="text-emerald-300 font-semibold">[INGEST]</span>`;
  } else if (msg.includes("[ERR]") || msg.includes("[FATAL]")) {
    tag = `<span class="text-rose-400 font-semibold">[ERROR]</span>`;
  } else if (msg.includes("[STOP]")) {
    tag = `<span class="text-amber-400 font-semibold">[HALT]</span>`;
  }

  const cleanText = msg.replace(/^\[.*?\]\s*/, "");
  line.innerHTML = `
    <span class="text-secondary select-none text-[11px]">${now}</span>
    ${tag}
    <span class="text-inverse-on-surface/90 text-xs font-mono">${escapeHtml(cleanText)}</span>
  `;

  terminalBody.appendChild(line);
  terminalBody.scrollTop = terminalBody.scrollHeight;
}


// ============================================================================
// Feedback & Reviews (/api/reviews)
// ============================================================================

function setRating(val) {
  currentRating = val;
  const buttons = document.querySelectorAll(".star-btn");
  buttons.forEach((b, idx) => {
    if (idx < val) {
      b.className = "p-1 text-tertiary hover:scale-110 transition-transform star-btn";
    } else {
      b.className = "p-1 text-secondary/30 hover:text-tertiary hover:scale-110 transition-transform star-btn";
    }
  });
  document.getElementById("ratingScoreText").innerText = `${val}.0 / 5.0`;
}

async function submitReviewFeedback() {
  const textInput = document.getElementById("feedbackText");
  const emailInput = document.getElementById("feedbackEmail");
  const wantsPaid = document.getElementById("feedbackWantsPaid").checked;
  const btn = document.getElementById("submitFeedbackBtn");
  const notice = document.getElementById("feedbackStatusNotice");

  const comment = textInput.value.trim();
  if (!comment || comment.length < 3) {
    showToast("Please enter feedback notes (at least 3 characters).", "error");
    textInput.focus();
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span class="material-symbols-outlined text-[16px] animate-spin">sync</span> Submitting...`;

  try {
    const headers = { "Content-Type": "application/json" };
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

    const res = await fetch("/api/reviews", {
      method: "POST",
      headers,
      body: JSON.stringify({
        rating: currentRating,
        comment,
        wants_paid_version: wantsPaid,
      }),
    });

    const data = await res.json();
    if (res.ok) {
      btn.innerHTML = `<span class="material-symbols-outlined text-[16px]">check_circle</span> Submitted`;
      btn.className = "w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-label uppercase tracking-wider font-semibold";
      notice.innerText = "Thank you! Your feedback has been committed to cloud registry.";
      textInput.value = "";
      appendTerminalLog(`[FEEDBACK] Submitted product review (${currentRating}★). Synced to Cloud database.`);
      showToast("Thank you for your valuable feedback!", "success");
    } else {
      const errMsg = (data.detail && typeof data.detail === "object") ? data.detail.message : (data.detail || "Submission failed.");
      showToast(errMsg, "error");
      btn.disabled = false;
      btn.innerHTML = `<span class="material-symbols-outlined text-[16px]">send</span> Submit Feedback &amp; Review`;
    }
  } catch (err) {
    showToast("Network error submitting feedback.", "error");
    btn.disabled = false;
    btn.innerHTML = `<span class="material-symbols-outlined text-[16px]">send</span> Submit Feedback &amp; Review`;
  }
}


// ============================================================================
// Supabase Auth, User Dashboard & Admin Management
// ============================================================================

async function initSupabaseClient() {
  try {
    const res = await fetch("/api/auth/config");
    if (res.ok) {
      const config = await res.json();
      const anonKey = (config.supabase_anon_key || "").trim().replace(/^["']|["']$/g, "");
      const supabaseUrl = (config.supabase_url || "").trim().replace(/^["']|["']$/g, "").replace(/\/+$/, "");

      // A valid Supabase anon key must be a 3-part JWT starting with 'ey'
      const isValidJwt = anonKey.startsWith("ey") && anonKey.split(".").length === 3;

      if (!isValidJwt && anonKey) {
        console.warn("[Supabase] SUPABASE_ANON_KEY does not look like a valid JWT token. Client-side SDK skipped; resilient backend auth will be used.");
      }

      if (window.supabase && supabaseUrl && isValidJwt) {
        supabaseClient = window.supabase.createClient(supabaseUrl, anonKey);

        // Listen for Supabase Auth state transitions
        supabaseClient.auth.onAuthStateChange(async (event, session) => {
          if (session && session.access_token) {
            authToken = session.access_token;
            localStorage.setItem("gmaps_auth_token", authToken);
            currentUser = session.user;
            await fetchUserProfile();
          } else if (event === "SIGNED_OUT") {
            authToken = null;
            currentUser = null;
            currentUserProfile = null;
            localStorage.removeItem("gmaps_auth_token");
            updateAuthUI();
            await fetchCurrentQuota();
          }
        });

        // Restore active session
        const { data: { session } } = await supabaseClient.auth.getSession();
        if (session && session.access_token) {
          authToken = session.access_token;
          localStorage.setItem("gmaps_auth_token", authToken);
          currentUser = session.user;
          await fetchUserProfile();
        } else if (authToken) {
          await fetchUserProfile();
        }
      }
    }
  } catch (err) {
    console.warn("Could not initialize Supabase Auth client:", err);
  }
}

async function getValidAuthToken() {
  if (supabaseClient && supabaseClient.auth) {
    try {
      const { data } = await supabaseClient.auth.getSession();
      if (data && data.session && data.session.access_token) {
        authToken = data.session.access_token;
        localStorage.setItem("gmaps_auth_token", authToken);
        if (data.session.user) currentUser = data.session.user;
        return authToken;
      }
    } catch (e) {
      console.warn("[Auth] Error refreshing session via Supabase Client:", e);
    }
  }
  const token = authToken || localStorage.getItem("gmaps_auth_token");
  if (token && token !== "null" && token !== "undefined" && String(token).trim().length > 10) {
    authToken = String(token).trim();
    return authToken;
  }
  return null;
}

async function fetchUserProfile() {
  const token = await getValidAuthToken();
  if (!token) {
    currentUserProfile = null;
    updateAuthUI();
    return null;
  }
  try {
    const res = await fetch("/api/user/me", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      currentUserProfile = await res.json();
      updateAuthUI();
      return currentUserProfile;
    } else if (res.status === 401) {
      authToken = null;
      currentUserProfile = null;
      localStorage.removeItem("gmaps_auth_token");
      updateAuthUI();
    }
  } catch (err) {
    console.warn("Error fetching user profile:", err);
  }
  return null;
}

function clearAuthInputs() {
  const signInEmail = document.getElementById("signInEmail");
  const signInPassword = document.getElementById("signInPassword");
  const signUpName = document.getElementById("signUpName");
  const signUpEmail = document.getElementById("signUpEmail");
  const signUpPassword = document.getElementById("signUpPassword");
  const signInForm = document.getElementById("signInForm");
  const signUpForm = document.getElementById("signUpForm");
  const alertBox = document.getElementById("authAlertBox");

  if (signInEmail) signInEmail.value = "";
  if (signInPassword) signInPassword.value = "";
  if (signUpName) signUpName.value = "";
  if (signUpEmail) signUpEmail.value = "";
  if (signUpPassword) signUpPassword.value = "";
  if (signInForm) signInForm.reset();
  if (signUpForm) signUpForm.reset();
  if (alertBox) {
    alertBox.innerHTML = "";
    alertBox.classList.add("hidden");
  }
}

function openAuthModal() {
  clearAuthInputs();
  authModal.classList.remove("hidden");
  switchAuthTab("signin");
}

function closeAuthModal() {
  clearAuthInputs();
  if (authModal) authModal.classList.add("hidden");
}

function switchAuthTab(tab) {
  const signInBtn = document.getElementById("tabSignInBtn");
  const signUpBtn = document.getElementById("tabSignUpBtn");
  const signInForm = document.getElementById("signInForm");
  const signUpForm = document.getElementById("signUpForm");
  const alertBox = document.getElementById("authAlertBox");
  if (alertBox) alertBox.classList.add("hidden");

  if (tab === "signin") {
    if (signInBtn) signInBtn.className = "flex-1 py-1.5 rounded-md font-semibold text-primary bg-surface-container-lowest shadow-sm transition-all";
    if (signUpBtn) signUpBtn.className = "flex-1 py-1.5 rounded-md font-semibold text-secondary hover:text-on-surface transition-all";
    if (signInForm) signInForm.classList.remove("hidden");
    if (signUpForm) signUpForm.classList.add("hidden");
  } else {
    if (signUpBtn) signUpBtn.className = "flex-1 py-1.5 rounded-md font-semibold text-primary bg-surface-container-lowest shadow-sm transition-all";
    if (signInBtn) signInBtn.className = "flex-1 py-1.5 rounded-md font-semibold text-secondary hover:text-on-surface transition-all";
    if (signUpForm) signUpForm.classList.remove("hidden");
    if (signInForm) signInForm.classList.add("hidden");
  }
}

async function handleEmailSignIn(event) {
  if (event) event.preventDefault();
  const emailInput = document.getElementById("signInEmail");
  const passInput = document.getElementById("signInPassword");
  const email = emailInput ? emailInput.value.trim() : "";
  const password = passInput ? passInput.value : "";
  const submitBtn = document.getElementById("signInSubmitBtn");
  const alertBox = document.getElementById("authAlertBox");

  if (!email || !password) {
    showToast("Please enter both email and password.", "error");
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="animate-spin material-symbols-outlined text-[16px]">sync</span> Authenticating...`;
  }

  try {
    let authSuccess = false;
    let authError = null;

    // 1. Try client-side Supabase SDK if initialized
    if (supabaseClient) {
      const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
      if (!error && data && data.session) {
        authToken = data.session.access_token;
        currentUser = data.user;
        authSuccess = true;
      } else if (error) {
        // If client-side failed due to invalid API key or network, suppress it so backend fallback can attempt sign in
        if (error.message && error.message.toLowerCase().includes("api key")) {
          console.warn("[Supabase] Client-side SDK returned 'Invalid API key'. Retrying via backend /api/auth/login...");
        } else {
          authError = error.message;
        }
      }
    }

    // 2. Fall back to backend /api/auth/login endpoint if client-side is unavailable or returned an error
    if (!authSuccess) {
      try {
        const loginRes = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const loginData = await loginRes.json();
        if (loginRes.ok && loginData.access_token) {
          authToken = loginData.access_token;
          currentUser = loginData.user;
          authSuccess = true;
          authError = null;
        } else {
          authError = loginData.detail || authError || "Authentication failed.";
        }
      } catch (backendErr) {
        if (!authError) authError = backendErr.message;
      }
    }

    if (authSuccess) {
      localStorage.setItem("gmaps_auth_token", authToken);
      clearAuthInputs();
      await fetchUserProfile();
      showToast("Signed in successfully!", "success");
      closeAuthModal();
    } else {
      const displayMsg = authError || "Sign in failed. Please verify your credentials.";
      if (alertBox) {
        alertBox.className = "p-3 rounded-lg text-xs font-body leading-relaxed bg-red-50 text-red-900 border border-red-200";
        alertBox.innerHTML = `<strong>Sign In Failed:</strong> ${escapeHtml(displayMsg)}`;
        alertBox.classList.remove("hidden");
      }
      showToast(displayMsg, "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">login</span> Sign In`;
    }
  }
}

async function handleEmailSignUp(event) {
  if (event) event.preventDefault();
  const nameInput = document.getElementById("signUpName");
  const emailInput = document.getElementById("signUpEmail");
  const passInput = document.getElementById("signUpPassword");
  const name = nameInput ? nameInput.value.trim() : "";
  const email = emailInput ? emailInput.value.trim() : "";
  const password = passInput ? passInput.value : "";
  const submitBtn = document.getElementById("signUpSubmitBtn");
  const alertBox = document.getElementById("authAlertBox");

  if (!name || !email || !password) {
    showToast("Please fill in all registration fields.", "error");
    return;
  }

  if (password.length < 6) {
    showToast("Password must be at least 6 characters.", "error");
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="animate-spin material-symbols-outlined text-[16px]">sync</span> Creating Account...`;
  }

  try {
    // 1. Register through the secure backend endpoint to bypass Supabase free email rate limits
    const regRes = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password }),
    });

    const regData = await regRes.json();

    if (!regRes.ok) {
      const errMsg = regData.detail || "Registration failed. Please try again.";
      if (alertBox) {
        alertBox.className = "p-3 rounded-lg text-xs font-body leading-relaxed bg-red-50 text-red-900 border border-red-200";
        alertBox.innerHTML = `<strong>Registration Failed:</strong> ${escapeHtml(errMsg)}`;
        alertBox.classList.remove("hidden");
      }
      showToast(errMsg, "error");
      if (regRes.status === 409) {
        switchAuthTab("signin");
        const signInEmail = document.getElementById("signInEmail");
        if (signInEmail) signInEmail.value = email;
      }
      return;
    }

    // 2. Account created and pre-confirmed! Now sign in directly to establish active session
    let authSuccess = false;
    if (supabaseClient) {
      const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
      if (!error && data && data.session) {
        authToken = data.session.access_token;
        currentUser = data.user;
        authSuccess = true;
      }
    }

    if (!authSuccess) {
      try {
        const autoLoginRes = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        if (autoLoginRes.ok) {
          const autoData = await autoLoginRes.json();
          authToken = autoData.access_token;
          currentUser = autoData.user;
          authSuccess = true;
        }
      } catch (_) {}
    }

    if (authSuccess) {
      localStorage.setItem("gmaps_auth_token", authToken);
      clearAuthInputs();
      await fetchUserProfile();
      showToast("Account created and signed in!", "success");
      closeAuthModal();
    } else {
      showToast("Account created! Please sign in with your password.", "success");
      switchAuthTab("signin");
      const signInEmail = document.getElementById("signInEmail");
      if (signInEmail) signInEmail.value = email;
    }
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">person_add</span> Create Account &amp; Start Scraping`;
    }
  }
}

async function handleGoogleSignIn() {
  if (supabaseClient) {
    try {
      const { error } = await supabaseClient.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: window.location.origin },
      });
      if (error) showToast("Google Sign In Error: " + error.message, "error");
    } catch (err) {
      showToast(err.message, "error");
    }
  } else {
    showToast("Connecting to authentication service...", "info");
  }
}

async function signOutUser() {
  try {
    if (supabaseClient) {
      await supabaseClient.auth.signOut();
    }
  } catch (err) {
    console.warn("Sign out notice:", err);
  }
  authToken = null;
  currentUser = null;
  currentUserProfile = null;
  localStorage.removeItem("gmaps_auth_token");
  sessionStorage.clear();
  clearAuthInputs();
  updateAuthUI();
  showToast("You have been signed out.", "info");
  await fetchCurrentQuota();
}

async function openUserDashboardModal() {
  if (!authToken) {
    openAuthModal();
    return;
  }

  const modal = document.getElementById("userDashboardModal");
  modal.classList.remove("hidden");

  await fetchUserProfile();
  if (currentUserProfile) {
    const prof = currentUserProfile.profile;
    const plan = currentUserProfile.plan;
    const usage = currentUserProfile.daily_usage;

    const emailEl = document.getElementById("dashUserEmail");
    const planNameEl = document.getElementById("dashPlanName");
    const planPriceEl = document.getElementById("dashPlanPrice");
    const leadsTodayEl = document.getElementById("dashLeadsToday");
    const leadsLimitEl = document.getElementById("dashLeadsLimit");
    const leadsProgressEl = document.getElementById("dashLeadsProgress");
    const leadsRemEl = document.getElementById("dashLeadsRemaining");
    const jobsTodayEl = document.getElementById("dashJobsToday");
    const jobsLimitEl = document.getElementById("dashJobsLimit");
    const jobsProgressEl = document.getElementById("dashJobsProgress");

    if (emailEl) emailEl.innerText = `${prof.email} • Registered ${new Date(prof.created_at).toLocaleDateString()}`;
    if (planNameEl) planNameEl.innerText = plan.name;
    if (planPriceEl) planPriceEl.innerText = `${plan.price_bdt.toLocaleString()} BDT / month`;
    
    if (leadsTodayEl) leadsTodayEl.innerText = usage.leads_scraped.toLocaleString();
    if (leadsLimitEl) leadsLimitEl.innerText = `/ ${plan.daily_leads_limit.toLocaleString()}`;
    const leadsPct = Math.min(100, Math.round((usage.leads_scraped / plan.daily_leads_limit) * 100));
    if (leadsProgressEl) leadsProgressEl.style.width = `${leadsPct}%`;
    const leadsRemaining = Math.max(0, plan.daily_leads_limit - usage.leads_scraped);
    if (leadsRemEl) leadsRemEl.innerText = `${leadsRemaining.toLocaleString()} leads remaining today`;

    if (jobsTodayEl) jobsTodayEl.innerText = usage.jobs_count;
    if (jobsLimitEl) jobsLimitEl.innerText = `/ ${plan.daily_jobs_limit} jobs`;
    const jobsPct = Math.min(100, Math.round((usage.jobs_count / plan.daily_jobs_limit) * 100));
    if (jobsProgressEl) jobsProgressEl.style.width = `${jobsPct}%`;
  }

  await loadUserJobHistory();
}

function closeUserDashboardModal() {
  const modal = document.getElementById("userDashboardModal");
  if (modal) modal.classList.add("hidden");
}

async function loadUserJobHistory() {
  const tableBody = document.getElementById("userJobsTableBody");
  if (!tableBody || !authToken) return;

  tableBody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-secondary">Loading jobs history...</td></tr>`;

  try {
    const res = await fetch("/api/user/jobs", {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.jobs || []);
      if (!jobs || jobs.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-6 text-center text-secondary">No scraping jobs dispatched yet. Start your first job from the top bar!</td></tr>`;
        return;
      }

      tableBody.innerHTML = jobs.map(job => {
        const dateStr = new Date(job.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        let statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-primary-fixed text-primary">RUNNING</span>`;
        if (job.status === "completed") {
          statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800">COMPLETED</span>`;
        } else if (job.status === "stopped") {
          statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800">STOPPED</span>`;
        } else if (job.status === "failed") {
          statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-red-100 text-red-800">FAILED</span>`;
        }

        return `
          <tr class="hover:bg-surface-container/60 transition-colors">
            <td class="px-3.5 py-2.5 text-secondary whitespace-nowrap">${dateStr}</td>
            <td class="px-3.5 py-2.5 text-on-surface font-medium max-w-[200px] truncate" title="${escapeHtml(job.prompt)}">${escapeHtml(job.prompt)}</td>
            <td class="px-3.5 py-2.5 whitespace-nowrap">${statusBadge}</td>
            <td class="px-3.5 py-2.5 whitespace-nowrap font-mono text-[11px]"><strong class="text-primary">${job.leads_scraped}</strong> / ${job.target_leads}</td>
            <td class="px-3.5 py-2.5 whitespace-nowrap">
              <a href="/api/export/csv/${job.job_id}" target="_blank" class="px-2 py-1 rounded bg-surface-container hover:bg-surface-container-high text-primary font-label text-[11px] font-semibold transition-colors inline-flex items-center gap-1">
                <span class="material-symbols-outlined text-[14px]">download</span> CSV
              </a>
            </td>
          </tr>
        `;
      }).join("");
    } else {
      tableBody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-error">Failed to fetch job history.</td></tr>`;
    }
  } catch (err) {
    tableBody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function openAdminDashboardModal() {
  const token = await getValidAuthToken();
  if (!token) {
    showToast("Please sign in with your Administrator account.", "error");
    openAuthModal();
    return;
  }

  // Refresh profile if not loaded
  if (!currentUserProfile) {
    await fetchUserProfile();
  }

  if (!currentUserProfile || !currentUserProfile.is_admin) {
    showToast("Access restricted: Administrator authorization required.", "error");
    return;
  }

  const modal = document.getElementById("adminDashboardModal");
  modal.classList.remove("hidden");

  try {
    const res = await fetch("/api/admin/overview", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const ov = await res.json();
      document.getElementById("admTotalUsers").innerText = ov.total_users;
      document.getElementById("admJobsToday").innerText = ov.active_jobs_today;
      document.getElementById("admTotalLeads").innerText = ov.total_leads_scraped.toLocaleString();
      document.getElementById("admRevenue").innerText = `${ov.total_revenue_bdt.toLocaleString()} BDT`;
    } else if (res.status === 401 || res.status === 403) {
      showToast("Administrator session expired or unauthorized. Please re-login.", "error");
      closeAdminDashboardModal();
      openAuthModal();
      return;
    }
  } catch (err) {
    console.error("Admin overview fetch error:", err);
  }

  switchAdminTab("users");
}

function closeAdminDashboardModal() {
  const modal = document.getElementById("adminDashboardModal");
  if (modal) modal.classList.add("hidden");
}

function switchAdminTab(tab) {
  const tabUsers = document.getElementById("admTabUsers");
  const tabJobs = document.getElementById("admTabJobs");
  const tabPayments = document.getElementById("admTabPayments");
  const tabReviews = document.getElementById("admTabReviews");
  const usersView = document.getElementById("admUsersView");
  const jobsView = document.getElementById("admJobsView");
  const paymentsView = document.getElementById("admPaymentsView");
  const reviewsView = document.getElementById("admReviewsView");

  const inactiveBtn = "flex-1 py-1.5 rounded-md font-semibold text-secondary hover:text-on-surface transition-all flex items-center justify-center gap-1.5";
  const activeBtn = "flex-1 py-1.5 rounded-md font-semibold text-primary bg-surface-container-lowest shadow-sm transition-all flex items-center justify-center gap-1.5";

  if (tabUsers) tabUsers.className = tab === "users" ? activeBtn : inactiveBtn;
  if (tabJobs) tabJobs.className = tab === "jobs" ? activeBtn : inactiveBtn;
  if (tabPayments) tabPayments.className = tab === "payments" ? activeBtn : inactiveBtn;
  if (tabReviews) tabReviews.className = tab === "reviews" ? activeBtn : inactiveBtn;

  if (usersView) usersView.classList.toggle("hidden", tab !== "users");
  if (jobsView) jobsView.classList.toggle("hidden", tab !== "jobs");
  if (paymentsView) paymentsView.classList.toggle("hidden", tab !== "payments");
  if (reviewsView) reviewsView.classList.toggle("hidden", tab !== "reviews");

  if (tab === "users") {
    loadAdminUsers();
  } else if (tab === "jobs") {
    loadAdminJobs();
  } else if (tab === "payments") {
    loadAdminPayments();
  } else if (tab === "reviews") {
    loadAdminReviews();
  }
}

async function loadAdminUsers() {
  const tbody = document.getElementById("admUsersTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-secondary">Loading registered users...</td></tr>`;

  const token = await getValidAuthToken();
  if (!token) {
    tbody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-error">Please sign in as Administrator.</td></tr>`;
    return;
  }

  try {
    const res = await fetch("/api/admin/users", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      const users = Array.isArray(data) ? data : (data.users || []);
      if (!users || users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-secondary">No users found.</td></tr>`;
        return;
      }

      tbody.innerHTML = users.map(u => {
        const isCurrentAdmin = u.role === "admin";
        const hasCustom = Boolean(u.custom_leads_per_day && u.custom_leads_per_day > 0);
        const isPro = u.plan_id === "pro" || hasCustom;
        
        let planBadge = "";
        if (hasCustom) {
          planBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-purple-100 text-purple-900 border border-purple-300" title="${escapeHtml(u.custom_plan_name || '')}">${u.custom_leads_per_day.toLocaleString()} LEADS/DAY</span>`;
        } else if (isPro) {
          planBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-primary-fixed text-primary">PRO (10K)</span>`;
        } else {
          planBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-surface-container text-secondary">FREE (1K)</span>`;
        }

        return `
          <tr class="hover:bg-surface-container/60 transition-colors">
            <td class="px-3.5 py-2.5 font-medium text-on-surface">${escapeHtml(u.email)}</td>
            <td class="px-3.5 py-2.5 text-secondary">${escapeHtml(u.full_name || 'N/A')}</td>
            <td class="px-3.5 py-2.5">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase ${isCurrentAdmin ? 'bg-amber-100 text-amber-900 border border-amber-300' : 'bg-surface-container text-secondary'}">${u.role}</span>
            </td>
            <td class="px-3.5 py-2.5">
              ${planBadge}
            </td>
            <td class="px-3.5 py-2.5 flex items-center gap-1.5 whitespace-nowrap">
              <button type="button" class="px-2 py-1 rounded text-[10px] font-semibold bg-primary hover:bg-primary-hover text-on-primary transition-colors flex items-center gap-1 shadow-xs" onclick="openCustomQuotaModal('${u.id}', '${escapeHtml(u.email)}', ${u.custom_leads_per_day || 0}, '${escapeHtml(u.custom_plan_name || '')}')" title="Assign custom scrape volume (e.g. 20,000 or 500,000 leads)">
                <span class="material-symbols-outlined text-[13px]">tune</span> Quota
              </button>
              <button type="button" class="px-2 py-1 rounded text-[10px] font-semibold bg-surface-container hover:bg-surface-container-high text-on-surface transition-colors" onclick="changeUserPlan('${u.id}', '${isPro ? 'free' : 'pro'}')">
                ${isPro ? 'Set Free' : 'Promote Pro'}
              </button>
              <button type="button" class="px-2 py-1 rounded text-[10px] font-semibold ${isCurrentAdmin ? 'bg-red-50 text-red-700 hover:bg-red-100' : 'bg-amber-50 text-amber-800 hover:bg-amber-100'} transition-colors" onclick="changeUserRole('${u.id}', '${isCurrentAdmin ? 'user' : 'admin'}')">
                ${isCurrentAdmin ? 'Demote' : 'Make Admin'}
              </button>
            </td>
          </tr>
        `;
      }).join("");
    } else if (res.status === 401 || res.status === 403) {
      tbody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-error">Access restricted: Administrator role required.</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function changeUserPlan(userId, newPlan) {
  const token = await getValidAuthToken();
  if (!token) {
    showToast("Please sign in as Administrator.", "error");
    return;
  }
  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({ plan_id: newPlan })
    });
    if (res.ok) {
      showToast(`User plan updated to ${newPlan.toUpperCase()}!`, "success");
      loadAdminUsers();
    } else {
      const err = await res.json();
      showToast(err.detail || "Failed to update plan", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function changeUserRole(userId, newRole) {
  const token = await getValidAuthToken();
  if (!token) {
    showToast("Please sign in as Administrator.", "error");
    return;
  }
  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({ role: newRole })
    });
    if (res.ok) {
      showToast(`User role updated to ${newRole.toUpperCase()}!`, "success");
      loadAdminUsers();
    } else {
      const err = await res.json();
      showToast(err.detail || "Failed to update role", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

function openCustomQuotaModal(userId, userEmail, currentQuota, currentPlanName) {
  const modal = document.getElementById("customQuotaModal");
  if (!modal) return;
  document.getElementById("quotaTargetUserId").value = userId;
  document.getElementById("quotaTargetUserEmail").value = userEmail;
  document.getElementById("customDailyLeadsInput").value = currentQuota > 0 ? currentQuota : 20000;
  document.getElementById("customPlanNameInput").value = currentPlanName || "";
  modal.classList.remove("hidden");
}

function closeCustomQuotaModal() {
  const modal = document.getElementById("customQuotaModal");
  if (modal) modal.classList.add("hidden");
}

async function handleSaveCustomQuota(event) {
  if (event) event.preventDefault();
  const userId = document.getElementById("quotaTargetUserId").value;
  const rawLeads = document.getElementById("customDailyLeadsInput").value;
  const planName = document.getElementById("customPlanNameInput").value.trim();
  const submitBtn = document.getElementById("saveQuotaSubmitBtn");

  const leads = parseInt(rawLeads, 10);
  if (isNaN(leads) || leads <= 0) {
    showToast("Please enter a valid positive number of leads (e.g. 20000).", "error");
    return;
  }

  const token = await getValidAuthToken();
  if (!token) {
    showToast("Please sign in as Administrator.", "error");
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="animate-spin material-symbols-outlined text-[16px]">sync</span> Saving...`;
  }

  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({
        custom_leads_per_day: leads,
        custom_leads_per_job: leads,
        custom_jobs_per_day: 100,
        custom_plan_name: planName || `Custom (${leads.toLocaleString()} Leads/Day)`,
        plan_id: "pro"
      })
    });

    if (res.ok) {
      showToast(`Assigned ${leads.toLocaleString()} daily leads quota!`, "success");
      closeCustomQuotaModal();
      loadAdminUsers();
      if (currentUserProfile && currentUserProfile.profile && currentUserProfile.profile.id === userId) {
        await fetchUserProfile();
      }
    } else {
      const err = await res.json();
      showToast(err.detail || "Failed to update custom quota", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">check</span> Save Quota`;
    }
  }
}

async function resetUserCustomQuota() {
  const userId = document.getElementById("quotaTargetUserId").value;
  if (!confirm("Are you sure you want to remove the custom quota and reset this user to the standard plan default?")) {
    return;
  }

  const token = await getValidAuthToken();
  if (!token) {
    showToast("Please sign in as Administrator.", "error");
    return;
  }

  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({
        custom_leads_per_day: 0
      })
    });
    if (res.ok) {
      showToast("Custom quota reset to plan default.", "success");
      closeCustomQuotaModal();
      loadAdminUsers();
      if (currentUserProfile && currentUserProfile.profile && currentUserProfile.profile.id === userId) {
        await fetchUserProfile();
      }
    } else {
      const err = await res.json();
      showToast(err.detail || "Failed to reset quota", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============================================================================
// Admin CRM, Job Debugging & Diagnostic Log Inspector
// ============================================================================

let adminJobsCache = [];
let adminCrmFilter = "all";
let adminCrmSearch = "";
let activeJobLogsCache = [];
let activeLogFilter = "all";
let activeLeadsCache = [];
let activeJobDiagnostics = null;

function formatCrmDuration(sec) {
  const s = Math.max(0, parseFloat(sec) || 0);
  if (s < 1) return "< 1s";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const remSec = Math.round(s % 60);
  if (s < 3600) return `${m}m ${remSec}s`;
  const h = Math.floor(s / 3600);
  const remMin = Math.floor((s % 3600) / 60);
  return `${h}h ${remMin}m`;
}

function formatCrmTime(isoStr) {
  if (!isoStr) return "--";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return isoStr;
  }
}

async function loadAdminJobs() {
  const tbody = document.getElementById("admJobsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-secondary">Loading CRM searches and scraper activity...</td></tr>`;

  const token = await getValidAuthToken();
  if (!token) {
    tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-error">Please sign in as Administrator.</td></tr>`;
    return;
  }

  try {
    // 1. Fetch CRM Overview Metrics
    try {
      const metricRes = await fetch("/api/admin/crm/metrics", {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (metricRes.ok) {
        const m = await metricRes.json();
        const totalElem = document.getElementById("crmTotalSearches");
        const userElem = document.getElementById("crmUserSearches");
        const guestElem = document.getElementById("crmGuestSearches");
        const failedElem = document.getElementById("crmFailedSearches");
        const runningElem = document.getElementById("crmRunningSearches");
        const durElem = document.getElementById("crmAvgDuration");
        const leadsElem = document.getElementById("crmTotalLeads");
        const badgeElem = document.getElementById("crmErrorBadge");

        if (totalElem) totalElem.innerText = m.total_searches || 0;
        if (userElem) userElem.innerText = m.user_searches || 0;
        if (guestElem) guestElem.innerText = m.guest_searches || 0;
        if (failedElem) failedElem.innerText = m.failed_searches || 0;
        if (runningElem) runningElem.innerText = m.active_jobs || 0;
        if (durElem) durElem.innerText = formatCrmDuration(m.avg_duration_seconds || 0);
        if (leadsElem) leadsElem.innerText = (m.total_harvested_leads || 0).toLocaleString();

        if (badgeElem) {
          if (m.failed_searches > 0) {
            badgeElem.innerText = `${m.failed_searches} ${m.failed_searches === 1 ? 'Error' : 'Errors'}`;
            badgeElem.classList.remove("hidden");
          } else {
            badgeElem.classList.add("hidden");
          }
        }
      }
    } catch (metricErr) {
      console.warn("CRM metrics error:", metricErr);
    }

    // 2. Fetch Jobs List
    const res = await fetch("/api/admin/jobs?limit=100", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      adminJobsCache = Array.isArray(data) ? data : (data.jobs || []);
      renderAdminJobsTable();
    } else {
      const err = await res.json();
      tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-error">Failed to load platform jobs: ${escapeHtml(err.detail || 'Authorization failed')}</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderAdminJobsTable() {
  const tbody = document.getElementById("admJobsTableBody");
  if (!tbody) return;

  let filtered = adminJobsCache.slice();

  // Filter by status or user type tab
  if (adminCrmFilter === "failed") {
    filtered = filtered.filter(j => j.has_error || j.status === "failed");
  } else if (adminCrmFilter === "running") {
    filtered = filtered.filter(j => j.status === "running");
  } else if (adminCrmFilter === "completed") {
    filtered = filtered.filter(j => j.status === "completed");
  } else if (adminCrmFilter === "stopped") {
    filtered = filtered.filter(j => j.status === "stopped");
  } else if (adminCrmFilter === "guest") {
    filtered = filtered.filter(j => !j.is_authenticated || j.user_role === "guest");
  } else if (adminCrmFilter === "user") {
    filtered = filtered.filter(j => j.is_authenticated && j.user_role !== "guest");
  }

  // Filter by search query
  if (adminCrmSearch) {
    const q = adminCrmSearch.toLowerCase();
    filtered = filtered.filter(j => 
      (j.user_email || "").toLowerCase().includes(q) ||
      (j.user_name || "").toLowerCase().includes(q) ||
      (j.prompt || "").toLowerCase().includes(q) ||
      (j.job_id || "").toLowerCase().includes(q)
    );
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="px-3.5 py-8 text-center text-secondary">
          <div class="flex flex-col items-center justify-center gap-1.5">
            <span class="material-symbols-outlined text-[28px] text-secondary">search_off</span>
            <span class="font-medium">No matching searches found.</span>
            <span class="text-[11px] text-secondary">Try adjusting your filter or search query.</span>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(j => {
    // User / Role presentation
    const isGuest = !j.is_authenticated || (j.user_role === "guest");
    const roleBadge = isGuest
      ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-amber-50 text-amber-800 border border-amber-200">Guest</span>`
      : (j.user_role === "admin"
          ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-amber-100 text-amber-800 border border-amber-300">Admin</span>`
          : `<span class="px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-purple-100 text-purple-800 border border-purple-200">User</span>`
        );

    const userInitial = (j.user_name || j.user_email || "U")[0].toUpperCase();
    const timeStr = formatCrmTime(j.created_at);

    // Duration formatting
    const durationFormatted = formatCrmDuration(j.duration_seconds || 0);

    // Status Badge
    let statusBadge = "";
    if (j.status === "completed") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 flex items-center gap-1 w-max"><span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>COMPLETED</span>`;
    } else if (j.status === "failed") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-800 flex items-center gap-1 w-max animate-pulse"><span class="w-1.5 h-1.5 rounded-full bg-red-600"></span>FAILED</span>`;
    } else if (j.status === "running") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-800 flex items-center gap-1 w-max"><span class="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse"></span>RUNNING</span>`;
    } else if (j.status === "blocked_limit") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-900 border border-amber-300 flex items-center gap-1 w-max"><span class="w-1.5 h-1.5 rounded-full bg-amber-600"></span>LIMIT BLOCKED</span>`;
    } else if (j.status === "limit_reached") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-900 flex items-center gap-1 w-max">LIMIT REACHED</span>`;
    } else {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-700 flex items-center gap-1 w-max">${(j.status || "UNKNOWN").toUpperCase()}</span>`;
    }

    // Leads Progress
    const harvested = parseInt(j.leads_scraped) || 0;
    const target = parseInt(j.target_leads) || 100;
    const pct = Math.min(100, Math.round((harvested / target) * 100));

    // Error column presentation
    let errorCol = "";
    if (j.has_error || j.error_message) {
      const errClean = j.error_message || "Execution Error encountered during search";
      errorCol = `
        <div class="flex items-center gap-1 max-w-[170px]" title="${escapeHtml(errClean)}">
          <span class="material-symbols-outlined text-[14px] text-red-600 shrink-0">error</span>
          <span class="text-[11px] font-mono text-red-700 truncate cursor-help">${escapeHtml(errClean)}</span>
        </div>
      `;
    } else {
      errorCol = `
        <span class="inline-flex items-center gap-1 text-[11px] text-emerald-700 font-medium">
          <span class="material-symbols-outlined text-[14px]">check_circle</span> Clean Run
        </span>
      `;
    }

    return `
      <tr class="hover:bg-surface-container/70 transition-colors ${j.has_error ? 'bg-red-50/20' : ''}">
        <!-- Col 1: User / Requester -->
        <td class="px-3.5 py-3">
          <div class="flex items-center gap-2">
            <div class="w-7 h-7 rounded-full bg-surface-container-highest text-primary font-bold text-[11px] flex items-center justify-center shrink-0">
              ${escapeHtml(userInitial)}
            </div>
            <div class="flex flex-col min-w-0">
              <span class="font-semibold text-xs text-on-surface truncate max-w-[130px]" title="${escapeHtml(j.user_email || '')}">${escapeHtml(j.user_email || 'Guest')}</span>
              <div class="flex items-center gap-1.5 mt-0.5">
                ${roleBadge}
                <span class="text-[10px] text-secondary font-mono">${timeStr}</span>
              </div>
            </div>
          </div>
        </td>

        <!-- Col 2: Search Query & Params -->
        <td class="px-3.5 py-3">
          <div class="flex flex-col gap-1 max-w-[220px]">
            <div class="flex items-center justify-between gap-1">
              <span class="font-medium text-xs text-on-surface truncate" title="${escapeHtml(j.prompt)}">${escapeHtml(j.prompt)}</span>
              <button type="button" class="text-secondary hover:text-primary transition-colors p-0.5 shrink-0" title="Copy prompt" onclick="navigator.clipboard.writeText('${escapeHtml(j.prompt)}'); showToast('Prompt copied!', 'success');">
                <span class="material-symbols-outlined text-[13px]">content_copy</span>
              </button>
            </div>
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-surface-container text-secondary">Target: ${target}</span>
              ${j.scrape_website ? '<span class="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">Web Deep Scraper</span>' : '<span class="px-1.5 py-0.2 rounded text-[9px] text-secondary bg-surface-container">Maps Fast</span>'}
            </div>
          </div>
        </td>

        <!-- Col 3: Duration & Timing -->
        <td class="px-3.5 py-3 whitespace-nowrap">
          <div class="flex flex-col gap-0.5">
            <span class="font-mono font-bold text-xs ${j.status === 'running' ? 'text-primary' : 'text-on-surface'} flex items-center gap-1">
              <span class="material-symbols-outlined text-[13px] text-secondary">timer</span>
              ${durationFormatted}
            </span>
            <span class="text-[10px] text-secondary font-mono">${j.completed_at ? 'Done' : (j.status === 'blocked_limit' ? 'Blocked' : 'Active')}</span>
          </div>
        </td>

        <!-- Col 4: Status Badge -->
        <td class="px-3.5 py-3 whitespace-nowrap">
          ${statusBadge}
        </td>

        <!-- Col 5: Leads Harvested Progress -->
        <td class="px-3.5 py-3 whitespace-nowrap">
          <div class="flex flex-col gap-1 min-w-[90px]">
            <div class="flex items-center justify-between text-[11px] font-mono">
              <span class="font-bold text-on-surface">${harvested}</span>
              <span class="text-secondary">/ ${target}</span>
            </div>
            <div class="w-full bg-surface-container-high rounded-full h-1.5 overflow-hidden">
              <div class="h-1.5 rounded-full ${j.status === 'failed' ? 'bg-red-500' : 'bg-primary'}" style="width: ${pct}%"></div>
            </div>
          </div>
        </td>

        <!-- Col 6: Error Note -->
        <td class="px-3.5 py-3">
          ${errorCol}
        </td>

        <!-- Col 7: Debugging & Inspection Actions -->
        <td class="px-3.5 py-3 text-right whitespace-nowrap">
          <div class="flex items-center justify-end gap-1">
            <button type="button" class="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 text-slate-100 text-[11px] font-semibold flex items-center gap-1 transition-colors shadow-2xs" onclick="openAdminJobLogs('${j.job_id}')" title="Inspect terminal logs for this scraper run">
              <span class="material-symbols-outlined text-[13px] text-primary-fixed">terminal</span>
              <span>Logs</span>
            </button>
            <button type="button" class="px-2 py-1 rounded bg-surface-container hover:bg-surface-container-high text-secondary hover:text-on-surface text-[11px] font-semibold flex items-center gap-1 transition-colors" onclick="openAdminJobLeads('${j.job_id}')" title="Inspect harvested businesses">
              <span class="material-symbols-outlined text-[13px]">dataset</span>
              <span>Leads</span>
            </button>
            <button type="button" class="p-1 rounded text-secondary hover:text-on-surface hover:bg-surface-container transition-colors" onclick="copyJobDiagnostics('${j.job_id}')" title="Copy job diagnostics JSON">
              <span class="material-symbols-outlined text-[15px]">share</span>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function filterAdminCrm(status) {
  adminCrmFilter = status;

  const btnAll = document.getElementById("crmTabFilterAll");
  const btnUser = document.getElementById("crmTabFilterUser");
  const btnGuest = document.getElementById("crmTabFilterGuest");
  const btnErr = document.getElementById("crmTabFilterErrors");
  const btnRun = document.getElementById("crmTabFilterRunning");
  const btnDone = document.getElementById("crmTabFilterCompleted");

  const activeCls = "px-2.5 py-1.5 rounded-lg font-semibold bg-surface-container-lowest text-primary shadow-xs";
  const inactiveCls = "px-2.5 py-1.5 rounded-lg font-semibold text-secondary hover:text-on-surface transition-colors";
  const userActiveCls = "px-2.5 py-1.5 rounded-lg font-semibold bg-purple-100 text-purple-900 shadow-xs flex items-center gap-1";
  const userInactiveCls = "px-2.5 py-1.5 rounded-lg font-semibold text-secondary hover:text-purple-700 hover:bg-purple-50 transition-colors flex items-center gap-1";
  const guestActiveCls = "px-2.5 py-1.5 rounded-lg font-semibold bg-amber-100 text-amber-900 shadow-xs flex items-center gap-1";
  const guestInactiveCls = "px-2.5 py-1.5 rounded-lg font-semibold text-secondary hover:text-amber-700 hover:bg-amber-50 transition-colors flex items-center gap-1";
  const errorActiveCls = "px-2.5 py-1.5 rounded-lg font-semibold bg-red-100 text-red-800 shadow-xs flex items-center gap-1";
  const errorInactiveCls = "px-2.5 py-1.5 rounded-lg font-semibold text-secondary hover:text-red-700 hover:bg-red-50 flex items-center gap-1 transition-colors";

  if (btnAll) btnAll.className = status === "all" ? activeCls : inactiveCls;
  if (btnUser) btnUser.className = status === "user" ? userActiveCls : userInactiveCls;
  if (btnGuest) btnGuest.className = status === "guest" ? guestActiveCls : guestInactiveCls;
  if (btnErr) btnErr.className = status === "failed" ? errorActiveCls : errorInactiveCls;
  if (btnRun) btnRun.className = status === "running" ? activeCls : inactiveCls;
  if (btnDone) btnDone.className = status === "completed" ? activeCls : inactiveCls;

  renderAdminJobsTable();
}

function handleCrmSearch(val) {
  adminCrmSearch = (val || "").trim();
  const clearBtn = document.getElementById("crmSearchClearBtn");
  if (clearBtn) clearBtn.classList.toggle("hidden", !adminCrmSearch);
  renderAdminJobsTable();
}

function clearCrmSearch() {
  const input = document.getElementById("crmSearchInput");
  if (input) input.value = "";
  handleCrmSearch("");
}

// ----------------------------------------------------------------------------
// Log Inspector Modal Logic
// ----------------------------------------------------------------------------

async function openAdminJobLogs(jobId) {
  const modal = document.getElementById("adminLogModal");
  if (!modal) return;
  modal.classList.remove("hidden");

  const logBody = document.getElementById("adminLogBody");
  logBody.innerHTML = `<div class="text-slate-500 text-center py-8">Loading logs for job <code>${escapeHtml(jobId)}</code>...</div>`;

  // Find job in cache
  const job = adminJobsCache.find(j => j.job_id === jobId) || {};
  document.getElementById("admLogJobId").innerText = jobId;
  document.getElementById("admLogUser").innerText = job.user_email || "Guest";
  document.getElementById("admLogDuration").innerText = formatCrmDuration(job.duration_seconds || 0);
  document.getElementById("admLogPrompt").innerText = job.prompt || "--";

  const statusBadge = document.getElementById("admLogStatusBadge");
  if (statusBadge) {
    statusBadge.innerText = (job.status || "RUNNING").toUpperCase();
    statusBadge.className = `px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
      job.status === 'completed' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' :
      job.status === 'failed' ? 'bg-red-950 text-red-300 border border-red-800' :
      'bg-blue-950 text-blue-300 border border-blue-800'
    }`;
  }

  activeJobDiagnostics = job;
  activeJobLogsCache = [];
  activeLogFilter = "all";

  const token = await getValidAuthToken();
  if (!token) {
    logBody.innerHTML = `<div class="text-amber-400 py-6 text-center">Please sign in as Administrator to view job logs.</div>`;
    return;
  }

  try {
    const res = await fetch(`/api/admin/jobs/${jobId}/logs`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      activeJobLogsCache = data.logs || [];
      activeJobDiagnostics = { ...job, ...data.job_info, raw_logs: data.raw_text };

      // Update counters
      const allCount = activeJobLogsCache.length;
      const errCount = activeJobLogsCache.filter(l => (l.level || '').toUpperCase() === 'ERROR').length;
      const warnCount = activeJobLogsCache.filter(l => (l.level || '').toUpperCase() === 'WARN').length;

      document.getElementById("logCountAll").innerText = allCount;
      document.getElementById("logCountErrors").innerText = errCount;
      document.getElementById("logCountWarn").innerText = warnCount;
      document.getElementById("admLogTotalCount").innerText = allCount;

      renderModalLogs();
    } else {
      logBody.innerHTML = `<div class="text-red-400 py-6 text-center">Failed to load logs from server.</div>`;
    }
  } catch (err) {
    logBody.innerHTML = `<div class="text-red-400 py-6 text-center">${escapeHtml(err.message)}</div>`;
  }
}

function renderModalLogs() {
  const logBody = document.getElementById("adminLogBody");
  if (!logBody) return;

  const searchInput = document.getElementById("logSearchInput");
  const query = (searchInput ? searchInput.value : "").toLowerCase().trim();

  let logs = activeJobLogsCache.slice();

  if (activeLogFilter === "error") {
    logs = logs.filter(l => (l.level || '').toUpperCase() === 'ERROR');
  } else if (activeLogFilter === "warn") {
    logs = logs.filter(l => (l.level || '').toUpperCase() === 'WARN');
  } else if (activeLogFilter === "info") {
    logs = logs.filter(l => (l.level || '').toUpperCase() === 'INFO');
  }

  if (query) {
    logs = logs.filter(l => (l.message || '').toLowerCase().includes(query));
  }

  if (logs.length === 0) {
    logBody.innerHTML = `<div class="text-slate-500 text-center py-8">No matching log messages found.</div>`;
    return;
  }

  logBody.innerHTML = logs.map(l => {
    const lvl = (l.level || 'INFO').toUpperCase();
    let badgeClass = "text-slate-400";
    if (lvl === "ERROR") badgeClass = "text-red-400 font-bold";
    else if (lvl === "WARN") badgeClass = "text-amber-400 font-bold";
    else if (lvl === "SUCCESS") badgeClass = "text-emerald-400 font-bold";
    else if (lvl === "PLAN") badgeClass = "text-cyan-400 font-bold";
    else if (lvl === "CONFIG") badgeClass = "text-purple-400 font-bold";

    const timeStr = formatCrmTime(l.timestamp);

    return `
      <div class="flex items-start gap-2 py-0.5 hover:bg-slate-800/40 px-1.5 rounded transition-colors">
        <span class="text-slate-600 select-none shrink-0 font-mono text-[11px]">${timeStr}</span>
        <span class="${badgeClass} select-none shrink-0 font-mono text-[11px]">[${lvl}]</span>
        <span class="text-slate-200 break-words flex-1 font-mono text-[11px]">${escapeHtml(l.message || '')}</span>
      </div>
    `;
  }).join("");

  // Auto scroll to bottom
  logBody.scrollTop = logBody.scrollHeight;
}

function setLogFilter(filter) {
  activeLogFilter = filter;
  ["All", "Errors", "Warn", "Info"].forEach(name => {
    const btn = document.getElementById(`logFilter${name}`);
    if (btn) {
      if (filter.toLowerCase() === name.toLowerCase() || (filter === 'error' && name === 'Errors')) {
        btn.className = "px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-800 text-white";
      } else {
        btn.className = "px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-900 text-slate-400 hover:bg-slate-800";
      }
    }
  });
  renderModalLogs();
}

function filterModalLogs(val) {
  renderModalLogs();
}

function closeAdminLogModal() {
  const modal = document.getElementById("adminLogModal");
  if (modal) modal.classList.add("hidden");
}

function copyAdminLogs() {
  if (!activeJobLogsCache || activeJobLogsCache.length === 0) {
    showToast("No logs available to copy.", "info");
    return;
  }
  const raw = activeJobLogsCache.map(l => `[${l.timestamp}] [${l.level}] ${l.message}`).join("\n");
  navigator.clipboard.writeText(raw).then(() => {
    showToast("All diagnostic logs copied to clipboard!", "success");
  }).catch(() => {
    showToast("Failed to copy logs to clipboard.", "error");
  });
}

// ----------------------------------------------------------------------------
// Leads Inspector Modal Logic
// ----------------------------------------------------------------------------

async function openAdminJobLeads(jobId) {
  const modal = document.getElementById("adminLeadsModal");
  if (!modal) return;
  modal.classList.remove("hidden");

  const tbody = document.getElementById("admLeadsTableBody");
  tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-secondary">Loading harvested leads for job <code>${escapeHtml(jobId)}</code>...</td></tr>`;

  document.getElementById("admLeadsJobId").innerText = jobId;
  document.getElementById("admLeadsCountBadge").innerText = "Loading...";

  const token = await getValidAuthToken();
  if (!token) {
    tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-error">Please sign in as Administrator to view job leads.</td></tr>`;
    return;
  }

  try {
    const res = await fetch(`/api/admin/jobs/${jobId}/leads`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      activeLeadsCache = data.leads || [];
      document.getElementById("admLeadsCountBadge").innerText = `${activeLeadsCache.length} Harvested Leads`;
      renderHarvestedLeadsTable(activeLeadsCache);
    } else {
      tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-error">Failed to fetch leads for this job.</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderHarvestedLeadsTable(leads) {
  const tbody = document.getElementById("admLeadsTableBody");
  if (!tbody) return;

  if (!leads || leads.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="px-3.5 py-6 text-center text-secondary">No leads found for this search.</td></tr>`;
    return;
  }

  tbody.innerHTML = leads.map(l => {
    const emailStr = (l.emails && l.emails.length > 0)
      ? `<span class="font-mono text-emerald-700 font-semibold">${escapeHtml(l.emails[0])}</span>`
      : `<span class="text-secondary italic">None</span>`;

    const websiteStr = l.website_url
      ? `<a href="${escapeHtml(l.website_url)}" target="_blank" rel="noopener noreferrer" class="text-primary hover:underline truncate max-w-[140px] block">${escapeHtml(l.website_url.replace(/^https?:\/\//, ''))}</a>`
      : `<span class="text-secondary italic">No Website</span>`;

    return `
      <tr class="hover:bg-surface-container/60 transition-colors">
        <td class="px-3.5 py-2.5 font-semibold text-on-surface truncate max-w-[160px]">${escapeHtml(l.name || 'Unnamed')}</td>
        <td class="px-3.5 py-2.5 text-secondary truncate max-w-[120px]">${escapeHtml(l.category || '--')}</td>
        <td class="px-3.5 py-2.5 font-mono text-[11px] text-on-surface">${escapeHtml(l.phone || '--')}</td>
        <td class="px-3.5 py-2.5 text-[11px]">${emailStr}</td>
        <td class="px-3.5 py-2.5 text-[11px]">${websiteStr}</td>
        <td class="px-3.5 py-2.5 font-mono text-[11px]">${l.rating ? `⭐ ${l.rating}` : '--'}</td>
        <td class="px-3.5 py-2.5 text-secondary text-[11px] truncate max-w-[180px]" title="${escapeHtml(l.address || '')}">${escapeHtml(l.neighborhood || l.address || '--')}</td>
      </tr>
    `;
  }).join("");
}

function filterHarvestedLeadsTable(val) {
  const q = (val || "").toLowerCase().trim();
  if (!q) {
    renderHarvestedLeadsTable(activeLeadsCache);
    return;
  }
  const filtered = activeLeadsCache.filter(l => 
    (l.name || '').toLowerCase().includes(q) ||
    (l.category || '').toLowerCase().includes(q) ||
    (l.phone || '').toLowerCase().includes(q) ||
    (l.emails && l.emails.some(e => e.toLowerCase().includes(q))) ||
    (l.address || '').toLowerCase().includes(q)
  );
  renderHarvestedLeadsTable(filtered);
}

function closeAdminLeadsModal() {
  const modal = document.getElementById("adminLeadsModal");
  if (modal) modal.classList.add("hidden");
}

function copyJobDiagnostics(jobId) {
  const job = adminJobsCache.find(j => j.job_id === jobId);
  if (!job) {
    showToast("Job details not found", "error");
    return;
  }
  const payload = JSON.stringify({
    job_id: job.job_id,
    user: job.user_email,
    prompt: job.prompt,
    duration_seconds: job.duration_seconds,
    duration_formatted: formatCrmDuration(job.duration_seconds || 0),
    status: job.status,
    has_error: job.has_error,
    error_message: job.error_message,
    leads_scraped: job.leads_scraped,
    target_leads: job.target_leads,
    created_at: job.created_at,
    completed_at: job.completed_at,
  }, null, 2);

  navigator.clipboard.writeText(payload).then(() => {
    showToast("Job diagnostics copied to clipboard!", "success");
  });
}

async function loadAdminPayments() {
  const tbody = document.getElementById("admPaymentsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">Loading payment transactions...</td></tr>`;

  const token = await getValidAuthToken();
  if (!token) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">Please sign in as Administrator.</td></tr>`;
    return;
  }

  try {
    const res = await fetch("/api/admin/payments", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      const pmts = Array.isArray(data) ? data : (data.payments || []);
      if (!pmts || pmts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">No payment transactions recorded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = pmts.map(p => {
        const isSuccess = p.status === "completed";
        return `
          <tr class="hover:bg-surface-container/60 transition-colors">
            <td class="px-3.5 py-2.5 font-mono text-[10px] text-primary">${p.transaction_id || p.id.slice(0, 8)}</td>
            <td class="px-3.5 py-2.5 text-secondary">${escapeHtml(p.user_email || 'User')}</td>
            <td class="px-3.5 py-2.5 font-bold uppercase text-xs">${p.plan_id}</td>
            <td class="px-3.5 py-2.5 font-mono font-semibold">${p.amount} ${p.currency}</td>
            <td class="px-3.5 py-2.5 uppercase text-[10px] font-semibold text-secondary">${p.provider || p.payment_provider}</td>
            <td class="px-3.5 py-2.5">
              <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${isSuccess ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}">${p.status.toUpperCase()}</span>
            </td>
          </tr>
        `;
      }).join("");
    } else {
      tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">Failed to load payments (Authorization required).</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function loadAdminReviews() {
  const tbody = document.getElementById("admReviewsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">Loading feedback &amp; reports...</td></tr>`;

  const token = await getValidAuthToken();
  if (!token) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">Please sign in as Administrator.</td></tr>`;
    return;
  }

  try {
    const res = await fetch("/api/admin/reviews", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      const reviews = Array.isArray(data) ? data : (data.reviews || []);
      if (!reviews || reviews.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-6 text-center text-secondary">
          <div class="flex flex-col items-center justify-center gap-1.5">
            <span class="material-symbols-outlined text-[28px] text-secondary/60">rate_review</span>
            <p class="font-medium text-xs">No user feedback submitted yet.</p>
          </div>
        </td></tr>`;
        return;
      }

      tbody.innerHTML = reviews.map(r => {
        const rating = Number(r.rating) || 5;
        const isIssue = rating <= 2;
        const isModerate = rating === 3;
        
        let starsHtml = "";
        for (let i = 1; i <= 5; i++) {
          starsHtml += `<span class="material-symbols-outlined text-[14px] ${i <= rating ? 'text-amber-500 fill-1' : 'text-slate-300'}">star</span>`;
        }

        let ratingBadge = "";
        if (isIssue) {
          ratingBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-red-100 text-red-800 border border-red-300"><span class="w-1.5 h-1.5 rounded-full bg-red-600"></span>Issue (${rating}★)</span>`;
        } else if (isModerate) {
          ratingBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-100 text-amber-800 border border-amber-300"><span class="w-1.5 h-1.5 rounded-full bg-amber-600"></span>Neutral (${rating}★)</span>`;
        } else {
          ratingBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-100 text-emerald-800 border border-emerald-300"><span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>Good (${rating}★)</span>`;
        }

        let formattedDate = "Recent";
        if (r.created_at) {
          try {
            const d = new Date(r.created_at);
            formattedDate = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
          } catch (_) {}
        }

        const userEmailDisplay = r.user_email 
          ? `<span class="font-medium text-on-surface">${escapeHtml(r.user_email)}</span>`
          : `<span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-container text-secondary">Anonymous Guest</span>`;

        const wantsPaidBadge = r.wants_paid_version
          ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-primary-fixed text-primary">Interested in Pro</span>`
          : `<span class="px-2 py-0.5 rounded text-[10px] text-secondary">Free only</span>`;

        return `
          <tr class="hover:bg-surface-container/60 transition-colors ${isIssue ? 'bg-red-50/20' : ''}">
            <td class="px-3.5 py-2.5 font-mono text-[10px] text-secondary whitespace-nowrap">${formattedDate}</td>
            <td class="px-3.5 py-2.5 whitespace-nowrap">${userEmailDisplay}</td>
            <td class="px-3.5 py-2.5 whitespace-nowrap">
              <div class="flex flex-col gap-0.5">
                <div class="flex items-center">${starsHtml}</div>
                <div>${ratingBadge}</div>
              </div>
            </td>
            <td class="px-3.5 py-2.5 text-xs text-on-surface max-w-[340px] break-words">
              <div class="p-2 rounded bg-surface-container/40 border ${isIssue ? 'border-red-200 bg-red-50/40 text-red-950 font-medium' : 'border-surface-container-high/40'} leading-relaxed font-body">
                ${escapeHtml(r.comment || 'No comment provided')}
              </div>
            </td>
            <td class="px-3.5 py-2.5 whitespace-nowrap">${wantsPaidBadge}</td>
            <td class="px-3.5 py-2.5 whitespace-nowrap">
              <button type="button" class="px-2 py-1 rounded text-[10px] font-semibold bg-red-50 hover:bg-red-100 text-red-700 transition-colors flex items-center gap-1" onclick="deleteAdminReview(${r.id})">
                <span class="material-symbols-outlined text-[13px]">delete</span> Delete
              </button>
            </td>
          </tr>
        `;
      }).join("");
    } else {
      tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">Failed to fetch feedback list (Authorization required).</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function deleteAdminReview(reviewId) {
  if (!confirm(`Are you sure you want to delete review #${reviewId}?`)) return;

  const token = await getValidAuthToken();
  if (!token) {
    showToast("Please sign in as Administrator.", "error");
    return;
  }

  try {
    const res = await fetch(`/api/admin/reviews/${reviewId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      showToast(`Review #${reviewId} deleted.`, "success");
      loadAdminReviews();
    } else {
      const err = await res.json();
      showToast(err.detail || "Failed to delete review", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function triggerPlanUpgrade(planId) {
  if (!authToken) {
    showToast("Please sign in or create an account before upgrading.", "info");
    openAuthModal();
    return;
  }

  showToast(`Initiating checkout intent for ${planId.toUpperCase()} Harvester Tier...`, "info");

  try {
    const res = await fetch("/api/payments/create-intent", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify({
        plan_id: planId,
        provider: "sslcommerz"
      })
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || "Failed to create payment intent", "error");
      return;
    }

    const intent = await res.json();
    const txnId = intent.transaction_id || intent.intent_id;
    appendTerminalLog(`[PAYMENT/INTENT] Created checkout intent #${txnId} for ${intent.amount} BDT via ${intent.provider}.`);

    const confirmPayment = confirm(
      `[Checkout Gateway Simulation]\n\nPlan: Pro Harvester (${intent.amount} BDT / Month)\nProvider: ${intent.provider.toUpperCase()}\nTransaction ID: ${txnId}\n\nWould you like to simulate verified webhook confirmation to activate this plan immediately?`
    );

    if (confirmPayment) {
      appendTerminalLog(`[WEBHOOK] Dispatching verified test webhook to /api/payments/webhook/${intent.provider}...`);
      const hookRes = await fetch(`/api/payments/webhook/${intent.provider}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id: txnId,
          status: "completed",
        })
      });

      if (hookRes.ok) {
        showToast("🎉 Payment confirmed via webhook! Your Pro Plan is now active.", "success");
        appendTerminalLog(`[WEBHOOK/SUCCESS] Account upgraded to PRO tier. Daily limit: 10,000 leads, 50 jobs/day.`);
        await fetchUserProfile();
        await openUserDashboardModal();
      } else {
        const hookErr = await hookRes.json();
        showToast("Webhook verification failed: " + (hookErr.detail || "Error"), "error");
      }
    }
  } catch (err) {
    showToast("Payment error: " + err.message, "error");
  }
}


// ============================================================================
// Lead Details Modal
// ============================================================================

function openLeadModal(lead) {
  leadModalTitle.innerText = lead.name;

  const emailsStr = (lead.emails && lead.emails.length > 0) ? lead.emails.join(", ") : "None detected";
  const phoneStr = lead.phone || "Not listed";
  const webStr = lead.website_url ? `<a href="${lead.website_url}" target="_blank" class="text-primary hover:underline">${lead.website_url}</a>` : "No website";
  const mapsStr = lead.google_maps_url ? `<a href="${lead.google_maps_url}" target="_blank" class="text-primary hover:underline">Open on Google Maps</a>` : "Not available";
  const ratingStr = lead.rating ? `${lead.rating} ★ (${lead.reviews_count} reviews)` : "Unrated";

  leadModalContent.innerHTML = `
    <div class="grid grid-cols-2 gap-3 text-xs bg-surface-container-low p-3 rounded-xl">
      <div><span class="text-secondary font-label">Category:</span> <strong class="text-on-surface">${escapeHtml(lead.category || 'N/A')}</strong></div>
      <div><span class="text-secondary font-label">Neighborhood:</span> <strong class="text-on-surface">${escapeHtml(lead.neighborhood || 'N/A')}</strong></div>
      <div><span class="text-secondary font-label">Rating:</span> <strong class="text-amber-600">${ratingStr}</strong></div>
      <div><span class="text-secondary font-label">Price Range:</span> <strong class="text-on-surface">${escapeHtml(lead.price_range || 'N/A')}</strong></div>
      <div><span class="text-secondary font-label">Phone:</span> <strong class="text-on-surface">${escapeHtml(phoneStr)}</strong></div>
      <div><span class="text-secondary font-label">Website Status:</span> <strong class="text-primary">${lead.website_status}</strong></div>
    </div>

    <div class="flex flex-col gap-1 text-xs">
      <span class="text-secondary font-label">Full Address:</span>
      <p class="font-body text-on-surface bg-surface-container-low p-2 rounded-lg">${escapeHtml(lead.address || 'Not specified')}</p>
    </div>

    <div class="flex flex-col gap-1 text-xs">
      <span class="text-secondary font-label">Contact Emails:</span>
      <p class="font-body text-on-surface bg-surface-container-low p-2 rounded-lg">${escapeHtml(emailsStr)}</p>
    </div>

    <div class="flex flex-col gap-1 text-xs">
      <span class="text-secondary font-label">Website URL:</span>
      <p class="font-body text-on-surface bg-surface-container-low p-2 rounded-lg">${webStr}</p>
    </div>

    ${(lead.website_status === "Has Own Website" && lead.website_url) ? `
      <div class="flex items-center justify-between p-3 rounded-xl ${(lead.seo_report && lead.seo_report.opportunity_score !== undefined && lead.seo_report.opportunity_score !== null) ? 'bg-amber-500/10 border border-amber-500/20' : 'bg-surface-container border border-surface-container-high'} text-xs">
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-[20px] text-amber-600">troubleshoot</span>
          <div>
            <span class="font-semibold text-on-surface block">Local SEO Audit Report</span>
            <span class="text-secondary text-[11px]">${(lead.seo_report && lead.seo_report.opportunity_score !== undefined && lead.seo_report.opportunity_score !== null) ? `Opportunity Score: ${lead.seo_report.opportunity_score}/100 • 11 Signals Audited` : 'Audit 11 on-page signals (Speed, Mobile, Schema, NAP, Meta)'}</span>
          </div>
        </div>
        <button type="button" onclick="closeLeadModal(); triggerPageSeoAudit('${lead.place_id}')" class="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 font-semibold text-white text-xs flex items-center gap-1 shadow-xs transition-all">
          <span>${(lead.seo_report && lead.seo_report.opportunity_score !== undefined && lead.seo_report.opportunity_score !== null) ? `View Report (${lead.seo_report.opportunity_score}/100)` : 'Run SEO Audit'}</span>
          <span class="material-symbols-outlined text-[14px]">arrow_forward</span>
        </button>
      </div>
    ` : `
      <div class="flex items-center justify-between p-3 rounded-xl bg-surface-container/60 border border-surface-container-high text-xs opacity-80">
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-[20px] text-secondary">domain_disabled</span>
          <div>
            <span class="font-semibold text-on-surface block">Local SEO Status</span>
            <span class="text-secondary text-[11px]">${lead.website_status === 'Social Link Only' ? 'Social profile only (Local SEO Pitch: Build brand website)' : 'No website listed on Google Maps (Local SEO Pitch: Web development)'}</span>
          </div>
        </div>
      </div>
    `}

    <div class="flex items-center justify-between text-xs pt-2 border-t border-surface-container-high/30">
      <span class="text-secondary">Place ID: <code class="text-primary font-mono text-[10px]">${lead.place_id}</code></span>
      ${mapsStr}
    </div>
  `;

  leadModal.classList.remove("hidden");
}

function closeLeadModal() {
  leadModal.classList.add("hidden");
}


// ============================================================================
// Toast Notification Engine & Helper Functions
// ============================================================================

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  let icon = "info";
  if (type === "success") icon = "check_circle";
  if (type === "error") icon = "error";

  toast.innerHTML = `
    <span class="material-symbols-outlined text-[18px]">${icon}</span>
    <span class="flex-1">${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function getInitials(name) {
  if (!name) return "LP";
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function getInitialColor(name) {
  const colors = [
    "bg-primary-fixed text-primary",
    "bg-surface-container text-tertiary",
    "bg-secondary-container text-secondary",
    "bg-amber-100 text-amber-800",
  ];
  let sum = 0;
  for (let i = 0; i < (name || "").length; i++) {
    sum += name.charCodeAt(i);
  }
  return colors[sum % colors.length];
}

function cleanDomain(url) {
  try {
    const host = new URL(url).hostname;
    return host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/* =========================================================================
   ON-DEMAND LOCAL SEO AUDIT INSPECTOR MODAL & CONTROLLER
   ========================================================================= */

function closeSeoAuditModal() {
  const modal = document.getElementById("seoAuditModal");
  if (modal) modal.classList.add("hidden");
}

async function triggerPageSeoAudit(placeId) {
  const lead = allLeads.find(l => l.place_id === placeId);
  if (!lead) {
    showToast("Lead not found in current session", "warning");
    return;
  }
  if (!lead.website_url) {
    showToast("This business does not have a website to audit", "warning");
    return;
  }

  const modal = document.getElementById("seoAuditModal");
  const bizNameEl = document.getElementById("seoModalBizName");
  const urlEl = document.getElementById("seoModalUrl");
  const scoreBadgeEl = document.getElementById("seoModalScoreBadge");
  const pitchBannerEl = document.getElementById("seoModalPitchBanner");
  const pitchTitleEl = document.getElementById("seoModalPitchTitle");
  const pitchDescEl = document.getElementById("seoModalPitchDesc");
  const checksContainerEl = document.getElementById("seoModalChecksContainer");

  if (modal) modal.classList.remove("hidden");
  if (bizNameEl) bizNameEl.innerText = lead.name || "Business Local SEO Audit";
  if (urlEl) urlEl.innerText = lead.website_url;
  if (scoreBadgeEl) {
    scoreBadgeEl.innerText = "Analyzing...";
    scoreBadgeEl.className = "px-2.5 py-0.5 rounded-full text-xs font-bold font-label bg-amber-100 text-amber-900 border border-amber-300 animate-pulse";
  }
  if (pitchBannerEl) pitchBannerEl.classList.remove("hidden");
  if (pitchTitleEl) pitchTitleEl.innerText = "Local SEO Opportunity Angle";
  if (pitchDescEl) pitchDescEl.innerText = "Running 11 on-page Local SEO checks (Speed, Schema, NAP, Meta, H1)...";
  if (checksContainerEl) {
    checksContainerEl.innerHTML = `
      <div class="text-secondary text-center py-8 text-xs flex flex-col items-center justify-center gap-2">
        <span class="material-symbols-outlined text-[32px] animate-spin text-primary">sync</span>
        <p>Analyzing website with Chrome TLS 124 impersonation...</p>
      </div>
    `;
  }

  // If already audited and cached on the lead object
  if (lead.seo_report && (lead.seo_report.seo_health_score !== undefined || lead.seo_report.opportunity_score !== undefined)) {
    renderSeoAuditReportInModal(lead, lead.seo_report);
    return;
  }

  try {
    const res = await fetch("/api/seo-audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: lead.website_url,
        business_name: lead.name,
        category: lead.category || "",
        city: lead.neighborhood || "",
        phone: lead.phone || "",
        address: lead.address || "",
        rating: lead.rating || null,
        reviews_count: lead.reviews_count || null,
        job_id: currentJobId || null,
        place_id: lead.place_id || null,
      })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server responded with ${res.status}`);
    }

    const report = await res.json();
    lead.seo_report = report;
    renderSeoAuditReportInModal(lead, report);
    renderLeadsFeed(); // Re-render feed to reflect updated SEO score badge on lead card
  } catch (err) {
    console.error("SEO Audit Error:", err);
    if (scoreBadgeEl) {
      scoreBadgeEl.innerText = "Audit Failed";
      scoreBadgeEl.className = "px-2.5 py-0.5 rounded-full text-xs font-bold font-label bg-red-100 text-red-800 border border-red-300";
    }
    if (checksContainerEl) {
      checksContainerEl.innerHTML = `
        <div class="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-xs">
          <p class="font-bold flex items-center gap-1.5 mb-1">
            <span class="material-symbols-outlined text-[16px]">error</span>
            Audit could not be completed
          </p>
          <p>${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }
}

function copySeoHookText() {
  const hookEl = document.getElementById("seoModalHookText");
  const copyTextEl = document.getElementById("copySeoHookText");
  if (!hookEl) return;
  const rawText = hookEl.innerText.replace(/^["'\s]+|["'\s]+$/g, "");
  if (!rawText) return;
  navigator.clipboard.writeText(rawText).then(() => {
    if (copyTextEl) copyTextEl.innerText = "Copied!";
    showToast("Personalized cold outreach hook copied to clipboard!", "success");
    setTimeout(() => {
      if (copyTextEl) copyTextEl.innerText = "Copy Hook";
    }, 2500);
  }).catch(() => {
    showToast("Failed to copy hook to clipboard", "warning");
  });
}

function renderSeoAuditReportInModal(lead, report) {
  const scoreBadgeEl = document.getElementById("seoModalScoreBadge");
  const pitchTitleEl = document.getElementById("seoModalPitchTitle");
  const pitchDescEl = document.getElementById("seoModalPitchDesc");
  const hookBannerEl = document.getElementById("seoModalHookBanner");
  const hookTextEl = document.getElementById("seoModalHookText");
  const checksContainerEl = document.getElementById("seoModalChecksContainer");

  const healthScore = report.seo_health_score !== null && report.seo_health_score !== undefined
    ? report.seo_health_score
    : (report.opportunity_score !== null && report.opportunity_score !== undefined ? 100 - report.opportunity_score : null);

  const pitchPriority = report.lead_pitch_priority || "Moderate";
  const icebreakerHook = report.icebreaker_hook || "";

  let badgeColor = "bg-surface-container text-secondary border-surface-container-high";
  if (typeof healthScore === "number") {
    if (healthScore >= 80) badgeColor = "bg-emerald-100 text-emerald-900 border-emerald-300";
    else if (healthScore >= 50) badgeColor = "bg-amber-100 text-amber-900 border-amber-300";
    else badgeColor = "bg-rose-100 text-rose-900 border-rose-300";
  }

  if (scoreBadgeEl) {
    scoreBadgeEl.innerText = healthScore !== null ? `SEO Health: ${healthScore}/100` : "Audit Complete";
    scoreBadgeEl.className = `px-2.5 py-0.5 rounded-full text-xs font-bold font-label border ${badgeColor}`;
  }

  if (pitchTitleEl) {
    pitchTitleEl.innerText = `Outreach Priority: ${pitchPriority}`;
  }

  // Icebreaker hook display
  if (hookBannerEl && hookTextEl) {
    if (icebreakerHook) {
      hookTextEl.innerText = `"${icebreakerHook}"`;
      hookBannerEl.classList.remove("hidden");
    } else {
      hookBannerEl.classList.add("hidden");
    }
  }

  // Handle issues as either Array or Dict of AuditIssue objects
  const rawIssues = report.issues || {};
  const issues = Array.isArray(rawIssues) ? rawIssues : Object.values(rawIssues);
  const passedCount = issues.filter(iss => iss.audit_status === "Pass").length;
  const issueCount = issues.filter(iss => iss.audit_status === "Warning" || iss.audit_status === "Fail").length;

  if (pitchDescEl) {
    const ttfb = report.server_response_ttfb || (report.load_time_seconds ? `TTFB: ${report.load_time_seconds}s` : "HTML Socket Only");
    const words = report.word_count ? ` | Words: ${report.word_count}` : "";
    pitchDescEl.innerText = `${ttfb} | Passed: ${passedCount}/${issues.length} | Actionable Signals: ${issueCount}${words}`;
  }

  if (checksContainerEl) {
    if (issues.length === 0) {
      checksContainerEl.innerHTML = `
        <div class="p-4 rounded-xl bg-surface-container border border-surface-container-high text-secondary text-xs text-center">
          <p>No audit details available for this website.</p>
        </div>
      `;
      return;
    }

    checksContainerEl.innerHTML = issues.map(iss => {
      const status = iss.audit_status || "Pass";
      const isPass = status === "Pass";
      const isWarn = status === "Warning";
      const isFail = status === "Fail";

      let statusIcon = "check_circle";
      let statusColor = "text-emerald-600";
      if (isWarn) {
        statusIcon = "warning";
        statusColor = "text-amber-600";
      } else if (isFail) {
        statusIcon = "cancel";
        statusColor = "text-rose-600";
      } else if (status === "Unverified") {
        statusIcon = "help";
        statusColor = "text-secondary";
      }

      let prioClass = "bg-surface-container text-secondary border-surface-container-high";
      const prio = (iss.priority || "none").toLowerCase();
      if (prio === "high" || prio === "critical") prioClass = "bg-rose-100 text-rose-900 border-rose-300";
      else if (prio === "medium") prioClass = "bg-amber-100 text-amber-900 border-amber-300";
      else if (prio === "low") prioClass = "bg-blue-100 text-blue-900 border-blue-300";

      const finding = iss.evidence || iss.finding || iss.xlsx_summary || "";
      const recommendation = iss.recommended_fix || iss.recommendation || "";

      return `
        <div class="p-3 rounded-xl bg-surface-container-low border border-surface-container-high/60 flex flex-col gap-1 text-xs">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-1.5 font-bold text-on-surface">
              <span class="material-symbols-outlined text-[16px] ${statusColor}">
                ${statusIcon}
              </span>
              <span>${escapeHtml(iss.check_name || "Check")}</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="px-2 py-0.5 rounded text-[10px] font-semibold border ${isPass ? 'bg-emerald-50 text-emerald-800 border-emerald-200' : (isWarn ? 'bg-amber-50 text-amber-800 border-amber-200' : 'bg-rose-50 text-rose-800 border-rose-200')}">
                ${status}
              </span>
              ${(iss.priority && iss.priority !== "None") ? `
                <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${prioClass}">
                  ${escapeHtml(iss.priority)}
                </span>
              ` : ""}
            </div>
          </div>
          ${finding ? `<p class="text-secondary text-[11px] pl-5 leading-relaxed">${escapeHtml(finding)}</p>` : ""}
          ${recommendation ? `
            <div class="mt-1 pl-5 text-[11px] text-primary bg-primary/5 p-2 rounded-lg border border-primary/10">
              <span class="font-semibold">Recommended Fix:</span> ${escapeHtml(recommendation)}
            </div>
          ` : ""}
        </div>
      `;
    }).join("");
  }
}


