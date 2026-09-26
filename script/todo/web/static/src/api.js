// Appels JSON au hub, sur la même origine. Le cookie de session part seul ;
// le jeton CSRF, rendu par /api/session, accompagne chaque POST.
let csrfToken = "";

export class ApiError extends Error {
    constructor(status) {
        super(`HTTP ${status}`);
        this.status = status;
    }
}

export function setCsrfToken(token) {
    csrfToken = token;
}

async function parse(response) {
    if (!response.ok) {
        throw new ApiError(response.status);
    }
    return response.json();
}

export async function getJson(path) {
    return parse(await fetch(path, {credentials: "same-origin"}));
}

export async function postJson(path, body) {
    const response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
        body: JSON.stringify(body),
    });
    return parse(response);
}
