import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, BarChart3, Bell, CheckCheck, ChevronRight, Database, FileClock,
  Gauge, Languages, LoaderCircle, LogOut, Mail, MessageSquare, Plus, RefreshCw,
  Search, Server, ShieldCheck, Ticket, TrendingUp, UserCog, Users, X
} from "lucide-react";

import { api, clearToken, getToken, setToken } from "./api/client";
import { createTranslator } from "./i18n";
import "./styles.css";

const BRAND_ICON = "/branding/icon-192.png";

const STATUS_KEYS = {
  OPEN: "open",
  IN_PROGRESS: "inProgress",
  RESOLVED: "resolved",
  CLOSED: "closed"
};
const PRIORITY_KEYS = { LOW: "low", MEDIUM: "medium", HIGH: "high", CRITICAL: "critical" };
const ROLE_KEYS = { SUPER_ADMIN: "superAdministrator", AGENT: "agent", USER: "user" };
const EVENT_KEYS = {
  "ticket.created": "ticketCreated",
  "ticket.updated": "ticketUpdated",
  "ticket.assigned": "ticketAssigned",
  "message.created": "messageCreated"
};
const ENTITY_KEYS = { ticket: "ticketEntity", message: "messageEntity", system: "systemEntity" };

const nextStatuses = (status) => ({
  OPEN: ["IN_PROGRESS"],
  IN_PROGRESS: ["RESOLVED"],
  RESOLVED: ["IN_PROGRESS", "CLOSED"],
  CLOSED: []
}[status] || []);

function LanguageSwitch({ language, setLanguage, compact = false }) {
  return (
    <div className={`language-switch ${compact ? "compact" : ""}`} aria-label="Language">
      <Languages size={16} />
      <button className={language === "ru" ? "selected" : ""} onClick={() => setLanguage("ru")} type="button">RU</button>
      <button className={language === "en" ? "selected" : ""} onClick={() => setLanguage("en")} type="button">EN</button>
    </div>
  );
}

function Spinner({ text }) {
  return <span className="button-progress"><LoaderCircle className="spin" size={17} />{text}</span>;
}

function BrandIcon({ className = "" }) {
  return <img className={`brand-icon ${className}`} src={BRAND_ICON} alt="" aria-hidden="true" />;
}

function Login({ onLogin, language, setLanguage, t }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [mode, setMode] = useState("login");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (mode === "register") {
        await api("/auth/register", {
          method: "POST",
          body: JSON.stringify({ email, password, full_name: fullName })
        });
      }
      const result = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password })
      });
      setToken(result.access_token);
      await onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-language"><LanguageSwitch language={language} setLanguage={setLanguage} /></div>
      <form className="card auth-card animate-in" onSubmit={submit}>
        <BrandIcon className="auth-logo" />
        <h1>{t("appName")}</h1>
        <p>{mode === "login" ? t("loginHint") : t("registerHint")}</p>
        {mode === "register" && (
          <label>{t("fullName")}<input required minLength="2" value={fullName} onChange={(e) => setFullName(e.target.value)} /></label>
        )}
        <label>{t("email")}<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>{t("password")}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={submitting}>
          {submitting ? <Spinner text={t("loading")} /> : mode === "login" ? t("signIn") : t("signUp")}
        </button>
        <button
          className="link-button auth-toggle"
          type="button"
          onClick={() => {
            setError("");
            setMode(mode === "login" ? "register" : "login");
          }}
        >
          {mode === "login" ? t("needAccount") : t("haveAccount")}
        </button>
      </form>
    </main>
  );
}

function TicketDialog({ ticket, canChat, onClose, onChanged, t }) {
  const [messages, setMessages] = useState([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  async function loadMessages() {
    try {
      const data = await api(`/tickets/${ticket.id}/messages`);
      setMessages(data);
      await api(`/conversations/${ticket.id}/read`, { method: "POST" });
      onChanged(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (canChat) loadMessages();
    else setLoading(false);
  }, [ticket.id, canChat]);

  async function send(event) {
    event.preventDefault();
    if (!body.trim()) return;
    setSending(true);
    try {
      await api(`/tickets/${ticket.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ body })
      });
      setBody("");
      await loadMessages();
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="ticket-modal card animate-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal-header">
          <div className="modal-heading">
            <div className="eyebrow">{t(PRIORITY_KEYS[ticket.priority])} · {t(STATUS_KEYS[ticket.status])}</div>
            <h2>{ticket.title}</h2>
          </div>
          <div className="modal-header-actions">
            <span className={`badge ${ticket.status.toLowerCase()}`}>{t(STATUS_KEYS[ticket.status])}</span>
            <button className="close-button" onClick={onClose} title={t("close")}><X /></button>
          </div>
        </header>

        <div className="modal-scroll">
          <p className="ticket-description">{ticket.description}</p>
          <div className="ticket-meta">
            <span><b>{t("author")}:</b> {displayName(ticket.creator?.full_name, t) || ticket.creator_id}</span>
            <span><b>{t("assignee")}:</b> {displayName(ticket.assignee?.full_name, t) || t("notAssigned")}</span>
          </div>
          {canChat && <>
            <h3 className="section-title"><MessageSquare size={18} /> {t("conversation")}</h3>
            <div className="messages">
              {loading && <div className="inline-loading"><LoaderCircle className="spin" /> {t("loading")}</div>}
              {!loading && messages.length === 0 && <div className="empty">{t("noMessages")}</div>}
              {messages.map((message) => (
                <div className="message animate-in" key={message.id}>
                  <div><b>{displayName(message.author?.full_name, t) || t("user")}</b><time>{new Date(message.created_at).toLocaleString(languageCode(t))}</time></div>
                  <p>{message.body}</p>
                </div>
              ))}
            </div>
          </>}
          {error && <div className="error">{error}</div>}
        </div>

        {canChat && ticket.status !== "CLOSED" && (
          <form className="modal-footer message-form" onSubmit={send}>
            <textarea placeholder={t("messagePlaceholder")} value={body} onChange={(e) => setBody(e.target.value)} />
            <button disabled={sending || !body.trim()}>
              {sending ? <Spinner text={t("sending")} /> : t("send")}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}

function languageCode(t) {
  return t("language") === "Язык" ? "ru-RU" : "en-US";
}

function displayName(name, t) {
  if (name === "System Administrator") {
    return languageCode(t) === "ru-RU" ? "Системный администратор" : "System Administrator";
  }
  return name;
}

function NotificationDialog({ notification, isAdmin, onClose, onOpenTicket, t }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="notification-modal card animate-modal" onMouseDown={(event) => event.stopPropagation()}>
        <button className="close-button floating-close" onClick={onClose}><X /></button>
        <div className="notification-icon"><Bell /></div>
        <small>{new Date(notification.created_at).toLocaleString(languageCode(t))}</small>
        <h2>{notificationTitle(notification, t)}</h2>
        <p>{localizeNotificationText(notification.body, t)}</p>
        {isAdmin && <div className="notification-type">{t("event")}: <b>{t(EVENT_KEYS[notification.event_type])}</b></div>}
        {notification.entity_id && (
          <button onClick={() => onOpenTicket(notification.entity_id)}>
            <Ticket size={17} /> {t("goToTicket")}
          </button>
        )}
      </section>
    </div>
  );
}

function localizeNotificationText(text, t) {
  const localizedStatuses = text
    ?.replaceAll("IN_PROGRESS", t("inProgress"))
    .replaceAll("RESOLVED", t("resolved"))
    .replaceAll("CLOSED", t("closed"))
    .replaceAll("OPEN", t("open"));
  if (languageCode(t) === "ru-RU") return localizedStatuses;

  return localizedStatuses
    ?.replace(/^Обращение «(.+)» успешно зарегистрировано\.$/, "Request “$1” was created successfully.")
    .replace(/^Для обращения «(.+)» назначен исполнитель\.$/, "An assignee was selected for request “$1”.")
    .replace(/^В обращении «(.+)» появилось сообщение: (.+)$/s, "New message in request “$1”: $2")
    .replace(/^Статус обращения «(.+)» изменён на «?(.+?)»?\.$/, "The status of request “$1” changed to “$2”.")
    .replace(/^В обращении «(.+)» изменён исполнитель\.$/, "The assignee for request “$1” was changed.")
    .replace(/^Обращение «(.+)» было обновлено\.$/, "Request “$1” was updated.");
}

function notificationTitle(notification, t) {
  const titleKeys = {
    "Обращение создано": "ticketCreated",
    "Обращение обновлено": "ticketUpdated",
    "Назначен исполнитель": "ticketAssigned",
    "Исполнитель изменён": "assigneeChanged",
    "Статус изменён": "ticketUpdated",
    "Новое сообщение": "messageCreated"
  };
  return t(titleKeys[notification.title] || EVENT_KEYS[notification.event_type]);
}

function SkeletonCards() {
  return <div className="grid">{[1, 2, 3].map((item) => <div className="card skeleton-card" key={item}><i /><i /><i /><i /></div>)}</div>;
}

function OverviewSkeleton() {
  return (
    <div className="overview-grid">
      {[1, 2, 3, 4, 5, 6].map((item) => (
        <div className="card overview-card overview-skeleton" key={item}><i /><i /><i /><i /></div>
      ))}
    </div>
  );
}

function AdminOverview({ analytics, tickets, auditLogs, systemHealth, setSection, t }) {
  const total = Object.values(analytics.by_status).reduce((sum, value) => sum + value, 0);
  const statusColors = {
    OPEN: "#356df3",
    IN_PROGRESS: "#f0a532",
    RESOLVED: "#2fbd75",
    CLOSED: "#8591a6"
  };
  let offset = 0;
  const gradientParts = Object.entries(analytics.by_status).map(([status, value]) => {
    const start = total ? (offset / total) * 360 : 0;
    offset += value;
    const end = total ? (offset / total) * 360 : 0;
    return `${statusColors[status]} ${start}deg ${end}deg`;
  });
  const maxDaily = Math.max(1, ...analytics.created_last_7_days.map((item) => item.count));
  const maxPriority = Math.max(1, ...Object.values(analytics.by_priority));
  const recentTickets = [...tickets].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 4);
  const healthItems = [
    ["apiService", "api", Server],
    ["database", "database", Database],
    ["redis", "redis", Activity],
    ["kafka", "kafka", BarChart3]
  ];

  return (
    <div className="overview-grid">
      <section className="card overview-card status-overview">
        <div className="panel-heading"><div><span>{t("requestsByStatus")}</span><h2>{total}</h2></div><TrendingUp /></div>
        <div className="status-chart-row">
          <div className="donut-chart" style={{ background: total ? `conic-gradient(${gradientParts.join(",")})` : "#e8edf4" }}>
            <div><b>{total}</b><small>{t("total")}</small></div>
          </div>
          <div className="chart-legend">
            {Object.entries(analytics.by_status).map(([status, value]) => (
              <div key={status}><i style={{ background: statusColors[status] }} /><span>{t(STATUS_KEYS[status])}</span><b>{value}</b></div>
            ))}
          </div>
        </div>
      </section>

      <section className="card overview-card priority-overview">
        <div className="panel-heading"><div><span>{t("requestsByPriority")}</span><h2>{Object.values(analytics.by_priority).reduce((a, b) => a + b, 0)}</h2></div><BarChart3 /></div>
        <div className="priority-bars">
          {Object.entries(analytics.by_priority).map(([priority, value]) => (
            <div key={priority}>
              <div><span>{t(PRIORITY_KEYS[priority])}</span><b>{value}</b></div>
              <i><em className={priority.toLowerCase()} style={{ width: `${(value / maxPriority) * 100}%` }} /></i>
            </div>
          ))}
        </div>
      </section>

      <section className="card overview-card weekly-overview">
        <div className="panel-heading"><div><span>{t("weeklyDynamics")}</span><h2>{analytics.created_last_7_days.reduce((sum, item) => sum + item.count, 0)}</h2></div><TrendingUp /></div>
        <div className="weekly-chart">
          {analytics.created_last_7_days.map((item) => (
            <div className="day-column" key={item.date}>
              <b>{item.count}</b>
              <i><em style={{ height: `${Math.max(5, (item.count / maxDaily) * 100)}%` }} /></i>
              <span>{new Date(`${item.date}T12:00:00`).toLocaleDateString(languageCode(t), { weekday: "short" })}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="card overview-card health-overview">
        <div className="panel-heading"><div><span>{t("infrastructure")}</span><h2>{healthItems.filter(([, key]) => systemHealth?.[key]?.status === "operational").length}/4</h2></div><Activity /></div>
        <div className="health-list">
          {healthItems.map(([label, key, Icon]) => {
            const service = systemHealth?.[key];
            const operational = service?.status === "operational";
            return (
              <div key={key}>
                <span className="health-icon"><Icon /></span>
                <div><b>{t(label)}</b><small>{operational ? t("operational") : t("unavailable")}</small></div>
                {service?.latency_ms != null && <em>{service.latency_ms} ms</em>}
                <i className={operational ? "online" : "offline"} />
              </div>
            );
          })}
        </div>
      </section>

      <section className="card overview-card recent-overview">
        <div className="panel-title-row"><h3>{t("recentRequests")}</h3><button onClick={() => setSection("tickets")}>{t("viewAll")}<ChevronRight /></button></div>
        <div className="recent-list">
          {recentTickets.length === 0 && <div className="empty">{t("noRecentRequests")}</div>}
          {recentTickets.map((ticket) => (
            <div key={ticket.id}>
              <span className={`recent-priority ${ticket.priority.toLowerCase()}`} />
              <div><b>{ticket.title}</b><small>{displayName(ticket.creator?.full_name, t) || ticket.creator_id}</small></div>
              <span className={`badge ${ticket.status.toLowerCase()}`}>{t(STATUS_KEYS[ticket.status])}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="card overview-card activity-overview">
        <div className="panel-title-row"><h3>{t("recentActivity")}</h3><button onClick={() => setSection("audit")}>{t("viewAll")}<ChevronRight /></button></div>
        <div className="activity-list">
          {auditLogs.length === 0 && <div className="empty">{t("noRecentActivity")}</div>}
          {auditLogs.slice(0, 5).map((log) => (
            <div key={log.id}>
              <span><FileClock /></span>
              <div><b>{t(EVENT_KEYS[log.action])}</b><small>{formatAuditPayload(log.payload, t)}</small></div>
              <time>{new Date(log.created_at).toLocaleString(languageCode(t), { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</time>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function Footer({ t }) {
  const year = new Date().getFullYear();
  return (
    <footer className="product-footer">
      <div className="footer-brand">
        <BrandIcon className="footer-logo" />
        <div>
          <strong>{t("footerProduct")}</strong>
          <p>{t("footerDescription")}</p>
        </div>
      </div>
      <nav className="footer-links" aria-label="Footer">
        <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">{t("footerApi")}</a>
        <a href="mailto:support@example.com">{t("footerSupport")}</a>
      </nav>
      <div className="footer-meta">
        <span className="system-status"><i />{t("footerStatus")}</span>
        <span>{t("footerVersion")} 1.0.0</span>
        <small>© {year} {t("footerProduct")}. {t("footerRights")}</small>
      </div>
    </footer>
  );
}

function Dashboard({ user, onLogout, language, setLanguage, t }) {
  const [section, setSection] = useState(user.role === "SUPER_ADMIN" ? "overview" : "tickets");
  const [tickets, setTickets] = useState([]);
  const [overviewTickets, setOverviewTickets] = useState([]);
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [systemHealth, setSystemHealth] = useState(null);
  const [unread, setUnread] = useState(0);
  const [unreadMessages, setUnreadMessages] = useState(0);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [selectedNotification, setSelectedNotification] = useState(null);
  const [form, setForm] = useState({ title: "", description: "", priority: "MEDIUM" });
  const [filters, setFilters] = useState({ status: "", q: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [emailNotificationsEnabled, setEmailNotificationsEnabled] = useState(user.email_notifications_enabled ?? true);

  async function load(silent = false) {
    if (silent) setRefreshing(true); else setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams();
      if (filters.status) query.set("status", filters.status);
      if (filters.q) query.set("q", filters.q);
      const suffix = query.toString() ? `?${query}` : "";
      const [ticketData, statsData, noticeData, countData, conversationData, messageCountData] = await Promise.all([
        api(`/tickets${suffix}`), api("/tickets/stats"), api("/notifications"),
        api("/notifications/unread-count"), api("/conversations"), api("/conversations/unread-count")
      ]);
      setTickets(ticketData); setStats(statsData); setNotifications(noticeData);
      setUnread(countData.unread); setConversations(conversationData); setUnreadMessages(messageCountData.unread);
      if (user.role === "SUPER_ADMIN") {
        const [userData, auditData, analyticsData, healthData, allTicketData] = await Promise.all([
          api("/users"),
          api("/audit-logs"),
          api("/tickets/analytics"),
          api("/system/health"),
          api("/tickets")
        ]);
        setUsers(userData);
        setAuditLogs(auditData);
        setAnalytics(analyticsData);
        setSystemHealth(healthData);
        setOverviewTickets(allTicketData);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), 15000);
    return () => clearInterval(timer);
  }, [filters.status]);

  async function createTicket(event) {
    event.preventDefault();
    setCreating(true);
    try {
      await api("/tickets", { method: "POST", body: JSON.stringify(form) });
      setForm({ title: "", description: "", priority: "MEDIUM" });
      await load(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  async function updateTicket(ticket, patch) {
    try {
      await api(`/tickets/${ticket.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load(true);
    } catch (err) {
      setError(err.message);
    }
  }

  async function openNotification(notification) {
    if (!notification.is_read) await api(`/notifications/${notification.id}/read`, { method: "PATCH" });
    setSelectedNotification({ ...notification, is_read: true });
    await load(true);
  }

  async function openLinkedTicket(ticketId) {
    try {
      const ticket = await api(`/tickets/${ticketId}`);
      setSelectedNotification(null); setSelectedTicket(ticket);
    } catch (err) { setError(err.message); }
  }

  async function readAll() {
    await api("/notifications/read-all", { method: "POST" });
    await load(true);
  }

  async function updateEmailPreference(enabled) {
    const previous = emailNotificationsEnabled;
    setEmailNotificationsEnabled(enabled);
    try {
      await api("/users/me/preferences", {
        method: "PATCH",
        body: JSON.stringify({ email_notifications_enabled: enabled })
      });
    } catch (err) {
      setEmailNotificationsEnabled(previous);
      setError(err.message);
    }
  }

  async function updateUserRole(userId, role) {
    try {
      await api(`/users/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) });
      await load(true);
    } catch (err) {
      setError(err.message);
    }
  }

  const titles = {
    overview: ["overview", "overviewSubtitle"],
    users: ["users", "usersSubtitle"],
    tickets: ["tickets", "ticketsSubtitle"],
    notifications: ["notifications", "notificationsSubtitle"],
    messages: ["messages", "messagesSubtitle"],
    audit: ["audit", "auditSubtitle"]
  };

  return (
    <main className="layout">
      <aside className="sidebar">
        <div className="brand"><BrandIcon />{t("appShort")}</div>
        <div className="user-box">
          <ShieldCheck size={18} /><div>{displayName(user.full_name, t)}<small>{user.email} · {t(ROLE_KEYS[user.role])}</small></div>
        </div>
        <nav>
          {user.role === "SUPER_ADMIN" && <button className={section === "overview" ? "nav active" : "nav"} onClick={() => setSection("overview")}><Gauge />{t("overview")}</button>}
          <button className={section === "tickets" ? "nav active" : "nav"} onClick={() => setSection("tickets")}><Ticket />{t("tickets")}</button>
          {user.role === "SUPER_ADMIN" && <button className={section === "users" ? "nav active" : "nav"} onClick={() => setSection("users")}><Users />{t("users")}</button>}
          <button className={section === "notifications" ? "nav active" : "nav"} onClick={() => setSection("notifications")}><Bell />{t("notifications")}{unread > 0 && <span className="counter">{unread}</span>}</button>
          {user.role !== "SUPER_ADMIN" && <button className={section === "messages" ? "nav active" : "nav"} onClick={() => setSection("messages")}><MessageSquare />{t("messages")}{unreadMessages > 0 && <span className="counter">{unreadMessages}</span>}</button>}
          {user.role === "SUPER_ADMIN" && <button className={section === "audit" ? "nav active" : "nav"} onClick={() => setSection("audit")}><FileClock />{t("audit")}</button>}
        </nav>
        <div className="sidebar-bottom">
          <LanguageSwitch language={language} setLanguage={setLanguage} compact />
          <button className="ghost" onClick={() => load(true)} disabled={refreshing}><RefreshCw className={refreshing ? "spin" : ""} />{t("refresh")}</button>
          <button className="ghost danger" onClick={onLogout}><LogOut />{t("logout")}</button>
        </div>
      </aside>

      <section className="page-shell">
        <div className="content">
          <header className="top animate-in">
            <div><h1>{t(titles[section][0])}</h1><p>{t(titles[section][1])}</p></div>
            <button className="icon-button" onClick={() => setSection("notifications")}><Bell />{unread > 0 && <span className="floating-counter">{unread}</span>}</button>
          </header>
          {error && <div className="error animate-in">{error}<button onClick={() => load()}>{t("retry")}</button></div>}

          <div className="section-transition" key={section}>
            {section === "overview" && loading && <OverviewSkeleton />}
            {section === "overview" && analytics && (
              <AdminOverview
                analytics={analytics}
                tickets={overviewTickets}
                auditLogs={auditLogs}
                systemHealth={systemHealth}
                setSection={setSection}
                t={t}
              />
            )}
            {section === "tickets" && <>
              {stats && <div className="stats">
                {["total", "open", "inProgress", "resolved", "closed"].map((key) => <div key={key}><span>{t(key)}</span><b>{stats[key === "inProgress" ? "in_progress" : key]}</b></div>)}
              </div>}
              {user.role === "USER" && (
                <form className="card form-row" onSubmit={createTicket}>
                  <input required minLength="3" placeholder={t("subjectPlaceholder")} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                  <input required minLength="5" placeholder={t("descriptionPlaceholder")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                    {Object.entries(PRIORITY_KEYS).map(([value, key]) => <option key={value} value={value}>{t(key)}</option>)}
                  </select>
                  <button disabled={creating}>{creating ? <Spinner text={t("creating")} /> : <><Plus />{t("create")}</>}</button>
                </form>
              )}
              <div className="filters card">
                <div className="search-input"><Search /><input placeholder={t("searchPlaceholder")} value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} /></div>
                <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
                  <option value="">{t("allStatuses")}</option>
                  {Object.entries(STATUS_KEYS).map(([value, key]) => <option key={value} value={value}>{t(key)}</option>)}
                </select>
                <button onClick={() => load()}><Search />{t("find")}</button>
              </div>
              {loading ? <SkeletonCards /> : <div className="grid">
                {tickets.map((ticket) => <article className="card ticket-card" key={ticket.id} onClick={() => setSelectedTicket(ticket)}>
                  <div className="ticket-head"><h3>{ticket.title}</h3><span className={`badge ${ticket.status.toLowerCase()}`}>{t(STATUS_KEYS[ticket.status])}</span></div>
                  <p>{ticket.description}</p>
                  <div className="ticket-facts">
                    <span><b>{t("priority")}:</b> {t(PRIORITY_KEYS[ticket.priority])}</span>
                    <span><b>{t("author")}:</b> {displayName(ticket.creator?.full_name, t) || ticket.creator_id}</span>
                    <span><b>{t("assignee")}:</b> {displayName(ticket.assignee?.full_name, t) || t("notAssigned")}</span>
                  </div>
                  {user.role === "AGENT" && <div className="actions single-action" onClick={(event) => event.stopPropagation()}>
                    <select onChange={(e) => e.target.value && updateTicket(ticket, { status: e.target.value })} defaultValue="">
                      <option value="">{t("status")}</option>
                      {nextStatuses(ticket.status).map((s) => <option key={s} value={s}>{t(STATUS_KEYS[s])}</option>)}
                    </select>
                  </div>}
                  {user.role === "SUPER_ADMIN" && <div className="actions single-action" onClick={(event) => event.stopPropagation()}>
                    <select onChange={(e) => e.target.value && updateTicket(ticket, { assignee_id: e.target.value })} defaultValue="">
                      <option value="">{t("assign")}</option>
                      {users.filter((u) => u.role === "AGENT" && u.is_active).map((u) => <option key={u.id} value={u.id}>{displayName(u.full_name, t)}</option>)}
                    </select>
                  </div>}
                  <ChevronRight className="card-arrow" />
                </article>)}
              </div>}
            </>}

            {section === "notifications" && <div>
              <section className="card preference-card">
                <div>
                  <Mail />
                  <div>
                    <h3>{t("emailNotifications")}</h3>
                    <p>{t("emailNotificationsHint")}</p>
                  </div>
                </div>
                <label className="switch-row">
                  <input
                    type="checkbox"
                    checked={emailNotificationsEnabled}
                    onChange={(event) => updateEmailPreference(event.target.checked)}
                  />
                  <span>{emailNotificationsEnabled ? t("enabled") : t("disabled")}</span>
                </label>
              </section>
              <div className="section-actions"><button onClick={readAll}><CheckCheck />{t("readAll")}</button></div>
              <div className="timeline">{notifications.length === 0 && <div className="card empty">{t("noNotifications")}</div>}
                {notifications.map((n) => <article className={`card timeline-item ${n.is_read ? "" : "unread"}`} key={n.id} onClick={() => openNotification(n)}>
                  <div className="notification-dot"><Bell /></div><div><h3>{notificationTitle(n, t)}</h3><p>{localizeNotificationText(n.body, t)}</p></div><time>{new Date(n.created_at).toLocaleString(languageCode(t))}</time>
                </article>)}
              </div>
            </div>}

            {section === "users" && (
              <div className="card users-table-wrap">
                <table className="users-table">
                  <thead><tr><th>{t("fullName")}</th><th>{t("email")}</th><th>{t("role")}</th><th>{t("accountStatus")}</th></tr></thead>
                  <tbody>{users.map((item) => (
                    <tr key={item.id}>
                      <td><div className="user-cell"><span><UserCog /></span><b>{displayName(item.full_name, t)}</b></div></td>
                      <td>{item.email}</td>
                      <td>
                        <select value={item.role} onChange={(event) => updateUserRole(item.id, event.target.value)}>
                          <option value="USER">{t("user")}</option>
                          <option value="AGENT">{t("agent")}</option>
                          <option value="SUPER_ADMIN">{t("superAdministrator")}</option>
                        </select>
                      </td>
                      <td><span className={`account-state ${item.is_active ? "active" : "blocked"}`}>{item.is_active ? t("active") : t("blocked")}</span></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}

            {section === "messages" && <div className="conversation-list">
              {conversations.length === 0 && <div className="card empty">{t("noConversations")}</div>}
              {conversations.map((c) => <article className={`card conversation-item ${c.unread_count > 0 ? "unread" : ""}`} key={c.ticket_id} onClick={async () => setSelectedTicket(await api(`/tickets/${c.ticket_id}`))}>
                <div className="conversation-avatar"><MessageSquare /></div>
                <div className="conversation-content"><div className="conversation-head"><h3>{c.ticket_title}</h3><span className={`badge ${c.ticket_status.toLowerCase()}`}>{t(STATUS_KEYS[c.ticket_status])}</span></div>
                  {c.last_message ? <p><b>{displayName(c.last_author_name, t)}:</b> {c.last_message}</p> : <p className="muted">{t("noMessages")}</p>}
                </div>
                <div className="conversation-side">{c.last_message_at && <time>{new Date(c.last_message_at).toLocaleString(languageCode(t))}</time>}{c.unread_count > 0 && <span className="counter">{c.unread_count}</span>}</div>
              </article>)}
            </div>}

            {section === "audit" && <div className="card table-wrap"><table>
              <thead><tr><th>{t("date")}</th><th>{t("action")}</th><th>{t("entity")}</th><th>{t("actor")}</th><th>{t("details")}</th></tr></thead>
              <tbody>{auditLogs.map((log) => <tr key={log.id}><td>{new Date(log.created_at).toLocaleString(languageCode(t))}</td><td><span className="event-name">{t(EVENT_KEYS[log.action])}</span></td><td>{t(ENTITY_KEYS[log.entity_type])}<br /><small>{log.entity_id}</small></td><td><small>{log.actor_id || t("system")}</small></td><td>{formatAuditPayload(log.payload, t)}</td></tr>)}</tbody>
            </table></div>}
          </div>
        </div>
        <Footer t={t} />
      </section>

      {selectedTicket && <TicketDialog ticket={selectedTicket} canChat={user.role !== "SUPER_ADMIN"} onClose={() => setSelectedTicket(null)} onChanged={load} t={t} />}
      {selectedNotification && <NotificationDialog notification={selectedNotification} isAdmin={user.role === "SUPER_ADMIN"} onClose={() => setSelectedNotification(null)} onOpenTicket={openLinkedTicket} t={t} />}
    </main>
  );
}

function formatAuditPayload(payload, t) {
  const parts = [];
  if (payload.title) parts.push(`${t("topic")}: ${payload.title}`);
  if (payload.message_preview) parts.push(`${t("message")}: ${payload.message_preview}`);
  if (payload.assignee_id) parts.push(t("assigneeAssigned"));
  if (payload.changes?.status) parts.push(`${t("newStatus")}: ${t(STATUS_KEYS[payload.changes.status])}`);
  if (payload.changes?.assignee_id) parts.push(t("assigneeChanged"));
  return parts.length ? parts.join("; ") : t("noExtraData");
}

function App() {
  const [language, setLanguageState] = useState(() => localStorage.getItem("interface_language") || "ru");
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(getToken()));
  const [booting, setBooting] = useState(true);
  const t = useMemo(() => createTranslator(language), [language]);

  function setLanguage(value) {
    localStorage.setItem("interface_language", value);
    document.documentElement.lang = value;
    document.title = value === "ru" ? "Система обработки обращений" : "Customer Support System";
    setLanguageState(value);
  }

  async function loadMe() {
    try { setUser(await api("/auth/me")); }
    catch { clearToken(); setUser(null); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = language === "ru" ? "Система обработки обращений" : "Customer Support System";
    if (getToken()) loadMe();
    const timer = setTimeout(() => setBooting(false), 700);
    return () => clearTimeout(timer);
  }, []);

  if (booting || loading) return (
    <div className="app-loader">
      <div className="preloader-glow" />
      <BrandIcon className="loader-mark" />
      <div className="loader-copy"><strong>{t("appName")}</strong><span>{t("loading")}</span></div>
      <div className="loader-track"><i /></div>
    </div>
  );
  if (!user) return <Login onLogin={loadMe} language={language} setLanguage={setLanguage} t={t} />;
  return <Dashboard user={user} onLogout={() => { clearToken(); setUser(null); }} language={language} setLanguage={setLanguage} t={t} />;
}

createRoot(document.getElementById("root")).render(<App />);
