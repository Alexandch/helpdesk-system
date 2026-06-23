const API_URL = import.meta.env.VITE_API_URL || "/api/v1";

const ERROR_TRANSLATIONS = {
  "Invalid email or password": ["Неверная электронная почта или пароль", "Invalid email or password"],
  "Invalid authentication token": ["Недействительный токен авторизации", "Invalid authentication token"],
  "User is inactive or not found": ["Пользователь не найден или заблокирован", "User is inactive or not found"],
  "Admin role required": ["Требуются права администратора", "Administrator permissions are required"],
  "User with this email already exists": ["Пользователь с такой электронной почтой уже существует", "A user with this email already exists"],
  "User not found": ["Пользователь не найден", "User not found"],
  "Ticket not found": ["Обращение не найдено", "Request not found"],
  "Notification not found": ["Уведомление не найдено", "Notification not found"],
  "Only admin can change status or assignee": ["Только администратор может менять статус или исполнителя", "Only an administrator can change the status or assignee"],
  "Only creator or admin can edit ticket content": ["Изменять обращение может только его автор или администратор", "Only the author or an administrator can edit this request"],
  "Assignee not found": ["Исполнитель не найден", "Assignee not found"],
  "Assignee must be an active admin": ["Исполнителем может быть только активный администратор", "The assignee must be an active administrator"],
  "Ticket must have assignee before moving to IN_PROGRESS": ["Перед переводом обращения в работу необходимо назначить исполнителя", "Assign an administrator before moving the request to In progress"],
  "Closed ticket cannot be reassigned": ["Закрытое обращение нельзя переназначить", "A closed request cannot be reassigned"],
  "Closed ticket does not accept new messages": ["В закрытое обращение нельзя добавлять сообщения", "A closed request does not accept new messages"],
  "Ticket or assignee not found": ["Обращение или исполнитель не найден", "Request or assignee not found"]
  ,"Only users can create tickets": ["Только клиенты могут создавать обращения", "Only customers can create requests"]
  ,"Super admin role required": ["Требуются права суперадминистратора", "Super administrator permissions are required"]
  ,"Assignee must be an active agent": ["Исполнителем может быть только активный сотрудник поддержки", "The assignee must be an active support agent"]
  ,"Users can only edit ticket content": ["Клиент может изменять только содержимое своего обращения", "Customers can only edit their request content"]
  ,"Agents can only change ticket status": ["Исполнитель может изменять только статус обращения", "Agents can only change the request status"]
  ,"Super admins can only assign agents": ["Суперадминистратор может только назначать исполнителей", "Super administrators can only assign agents"]
  ,"Super admins do not participate in customer conversations": ["Суперадминистраторы не участвуют в переписке с клиентами", "Super administrators do not participate in customer conversations"]
  ,"At least one active super admin is required": ["В системе должен оставаться хотя бы один активный суперадминистратор", "At least one active super administrator is required"]
  ,"You cannot deactivate your own account": ["Нельзя заблокировать собственную учётную запись", "You cannot deactivate your own account"]
};

function translateError(detail, status) {
  const english = localStorage.getItem("interface_language") === "en";
  if (!detail) return english ? `Request error (${status})` : `Ошибка запроса (${status})`;
  if (ERROR_TRANSLATIONS[detail]) return ERROR_TRANSLATIONS[detail][english ? 1 : 0];
  if (detail.startsWith("Invalid status transition:")) {
    return english ? "This request status transition is not allowed" : "Недопустимый переход между статусами обращения";
  }
  return detail;
}

export function getToken() {
  return sessionStorage.getItem("access_token");
}

export function setToken(token) {
  localStorage.removeItem("access_token");
  sessionStorage.setItem("access_token", token);
}

export function clearToken() {
  localStorage.removeItem("access_token");
  sessionStorage.removeItem("access_token");
}

export async function api(path, options = {}) {
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    }
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(translateError(data.detail, response.status));
  }

  if (response.status === 204) return null;
  return response.json();
}
