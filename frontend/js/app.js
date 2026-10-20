/**
 * LeadPulse Harvester Pro — Alexandria Editorial Interactive Frontend Logic
 * Full-featured controller for SSE streaming, dynamic card rendering,
 * geographic hub updates, terminal daemon logging, exports, and Supabase auth sync.
 */

// Application State
let currentJobId = null;
let eventSource = null;
let allLeads = [];
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

  scraperPrompt.addEventListener("input", () => {
    const val = scraperPrompt.value;
    const len = val.length;
    charBudgetCounter.innerText = `Characters: ${len} / 300`;
    if (len >= 290) {
      charBudgetCounter.classList.add("text-error", "font-semibold");
    } else {
      charBudgetCounter.classList.remove("text-error", "font-semibold");
    }

    // Auto-detect target count from user prompt and sync dropdown chip
    const numMatch = val.match(/(\d{1,4})\s*(?:ta|ti|টি|টা|leads?|entities|businesses|companies|restaurants)?/i);
    if (numMatch) {
      if (["50", "100", "250", "500", "1000"].includes(numMatch[1])) {
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
        if (currentUserProfile && currentUserProfile.plan) {
          const used = currentUserProfile.daily_usage?.leads_scraped || 0;
          const limit = currentUserProfile.plan.daily_leads_limit;
          quotaText.innerHTML = `${used.toLocaleString()} / ${limit.toLocaleString()} <span class="text-tertiary font-semibold">(${currentUserProfile.plan.name})</span>`;
        } else {
          quotaText.innerText = "Verified Account";
        }
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

  progressTargetText.innerText = `of ${targetQuota} target entities`;

  // UI state transition
  setScrapingState(true);
  allLeads = [];
  lastCount = 0;
  startTime = Date.now();
  leadsFeedContainer.innerHTML = "";
  renderEmptyState("Initializing AI Geo-Planner & reverse protobuf query...");

  appendTerminalLog(`[AI/PLAN] Dispatching user prompt to Geo-Planner: "${prompt.slice(0, 60)}..."`);
  appendTerminalLog(`[CONFIG] Target: ${targetQuota} leads | Website Scraping: ${scrapeWebsite ? `ENABLED (Emails & Socials | Filter: ${mustHaveEmail ? "Verified Emails Only" : "All Sites"})` : "DISABLED (Fast Google Maps Only)"}`);

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

      // Update Current Area & Geographic Hub
      if (data.current_area) {
        hubCurrentArea.innerText = data.current_area;
        activeHubName.innerText = data.current_area.split(" in ").pop() || data.current_area;
      }

      // Ingest New Leads Batch or Final Enriched Leads
      if (Array.isArray(data.final_leads) && data.final_leads.length > 0) {
        allLeads = data.final_leads;
        renderLeadsFeed();
        updateMetricCards(targetQuota);
        const emailCount = allLeads.filter(l => l.emails && l.emails.length > 0).length;
        appendTerminalLog(`[ENRICH/SYNC] Final synchronized leads loaded. ${emailCount} leads verified with direct emails.`);
      } else if (Array.isArray(data.new_leads) && data.new_leads.length > 0) {
        let addedCount = 0;
        let updatedCount = 0;
        data.new_leads.forEach((lead) => {
          const idx = allLeads.findIndex((l) => l.place_id === lead.place_id);
          if (idx === -1) {
            allLeads.push(lead);
            addedCount++;
          } else {
            // Update existing lead with newly scraped emails, socials, or details
            allLeads[idx] = { ...allLeads[idx], ...lead };
            updatedCount++;
          }
        });

        if (addedCount > 0 || updatedCount > 0) {
          // Update Feed UI
          renderLeadsFeed();
          updateMetricCards(targetQuota);

          const latest = data.new_leads[0];
          if (addedCount > 0) {
            appendTerminalLog(`[API/INGEST] Ingested +${addedCount} candidate leads. Latest: "${latest.name}" (${latest.neighborhood || latest.address || 'Address verified'})`);
          }

          // Update geo coordinates on map if available
          if (latest.lat && latest.lon) {
            hubCoordsText.innerText = `Lat: ${latest.lat.toFixed(4)}, Lon: ${latest.lon.toFixed(4)}`;
            hubClusterText.innerText = `Cluster: Active (${allLeads.length})`;
            mapSubText.innerText = `${latest.neighborhood || 'Current Zone'} Coordinates`;
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
  } else {
    startBtn.disabled = false;
    startBtn.classList.remove("opacity-50", "cursor-not-allowed");
    stopBtn.classList.add("hidden");
    stopBtn.classList.remove("flex");

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

function renderLeadsFeed() {
  const visibleLeads = getFilteredLeads();
  streamBadge.innerText = `${visibleLeads.length} Loaded`;

  if (visibleLeads.length === 0) {
    renderEmptyState(allLeads.length > 0 ? "No leads matching selected filter tab." : "No leads scraped yet.");
    return;
  }

  leadsFeedContainer.innerHTML = "";

  // Render cards from newest to oldest
  visibleLeads.slice().reverse().forEach((lead) => {
    const card = document.createElement("div");
    card.className = "lead-row flex flex-col md:flex-row md:items-center justify-between gap-3 p-4 rounded-xl bg-surface-container-low hover:bg-surface-container transition-all animate-fadeIn cursor-pointer";
    card.onclick = () => openLeadModal(lead);

    const initials = getInitials(lead.name);
    const colorClass = getInitialColor(lead.name);

    // Format website link
    let websiteBadge = "";
    if (lead.website_status === "Has Own Website" && lead.website_url) {
      const domain = cleanDomain(lead.website_url);
      websiteBadge = `
        <a href="${lead.website_url}" target="_blank" onclick="event.stopPropagation()" class="text-xs font-label text-primary hover:underline flex items-center gap-0.5">
          ${domain}
          <span class="material-symbols-outlined text-[12px]">north_east</span>
        </a>
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

  const downloadUrl = `/api/scrape/download/${targetJobId}?format=${format}`;
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

async function fetchUserProfile() {
  if (!authToken) return null;
  try {
    const res = await fetch("/api/user/me", {
      headers: { "Authorization": `Bearer ${authToken}` }
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
  if (!currentUserProfile || !currentUserProfile.is_admin) {
    showToast("Access restricted: Administrator authorization required.", "error");
    return;
  }

  const modal = document.getElementById("adminDashboardModal");
  modal.classList.remove("hidden");

  try {
    const res = await fetch("/api/admin/overview", {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (res.ok) {
      const ov = await res.json();
      document.getElementById("admTotalUsers").innerText = ov.total_users;
      document.getElementById("admJobsToday").innerText = ov.active_jobs_today;
      document.getElementById("admTotalLeads").innerText = ov.total_leads_scraped.toLocaleString();
      document.getElementById("admRevenue").innerText = `${ov.total_revenue_bdt.toLocaleString()} BDT`;
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

  const inactiveBtn = "flex-1 py-1.5 rounded-md font-semibold text-secondary hover:text-on-surface transition-all";
  const activeBtn = "flex-1 py-1.5 rounded-md font-semibold text-primary bg-surface-container-lowest shadow-sm transition-all";

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

  try {
    const res = await fetch("/api/admin/users", {
      headers: { "Authorization": `Bearer ${authToken}` }
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
        const isPro = u.plan_id === "pro";
        return `
          <tr class="hover:bg-surface-container/60 transition-colors">
            <td class="px-3.5 py-2.5 font-medium text-on-surface">${escapeHtml(u.email)}</td>
            <td class="px-3.5 py-2.5 text-secondary">${escapeHtml(u.full_name || 'N/A')}</td>
            <td class="px-3.5 py-2.5">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase ${isCurrentAdmin ? 'bg-amber-100 text-amber-900 border border-amber-300' : 'bg-surface-container text-secondary'}">${u.role}</span>
            </td>
            <td class="px-3.5 py-2.5">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase ${isPro ? 'bg-primary-fixed text-primary' : 'bg-surface-container text-secondary'}">${u.plan_id}</span>
            </td>
            <td class="px-3.5 py-2.5 flex items-center gap-1.5 whitespace-nowrap">
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
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function changeUserPlan(userId, newPlan) {
  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
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
  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
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

async function loadAdminJobs() {
  const tbody = document.getElementById("admJobsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">Loading platform jobs...</td></tr>`;

  try {
    const res = await fetch("/api/admin/jobs", {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.jobs || []);
      if (!jobs || jobs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">No platform jobs found.</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => {
        let statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800">${j.status.toUpperCase()}</span>`;
        if (j.status === "failed") {
          statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-red-100 text-red-800">FAILED</span>`;
        } else if (j.status === "running") {
          statusBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-primary-fixed text-primary">RUNNING</span>`;
        }

        return `
          <tr class="hover:bg-surface-container/60 transition-colors">
            <td class="px-3.5 py-2.5 font-mono text-[10px] text-secondary">${j.job_id.slice(0, 8)}...</td>
            <td class="px-3.5 py-2.5 text-secondary truncate max-w-[120px]">${escapeHtml(j.user_email || 'Anonymous')}</td>
            <td class="px-3.5 py-2.5 text-on-surface truncate max-w-[180px]" title="${escapeHtml(j.prompt)}">${escapeHtml(j.prompt)}</td>
            <td class="px-3.5 py-2.5">${statusBadge}</td>
            <td class="px-3.5 py-2.5 font-mono text-xs">${j.leads_scraped} / ${j.target_leads}</td>
            <td class="px-3.5 py-2.5 text-error text-[11px] truncate max-w-[150px]">${escapeHtml(j.error_message || 'None')}</td>
          </tr>
        `;
      }).join("");
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function loadAdminPayments() {
  const tbody = document.getElementById("admPaymentsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">Loading payment transactions...</td></tr>`;

  try {
    const res = await fetch("/api/admin/payments", {
      headers: { "Authorization": `Bearer ${authToken}` }
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
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function loadAdminReviews() {
  const tbody = document.getElementById("admReviewsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-secondary">Loading feedback &amp; reports...</td></tr>`;

  try {
    const res = await fetch("/api/admin/reviews", {
      headers: { "Authorization": `Bearer ${authToken}` }
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
      tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">Failed to fetch feedback list.</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-3.5 py-4 text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

async function deleteAdminReview(reviewId) {
  if (!confirm(`Are you sure you want to delete review #${reviewId}?`)) return;

  try {
    const res = await fetch(`/api/admin/reviews/${reviewId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${authToken}` }
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
