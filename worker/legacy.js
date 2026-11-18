// Compatibility for the address sent before the owner renamed the project.
export {Coordinator} from './src/index.js';
export default {
  fetch(request, env) {
    const url = new URL(request.url);
    return Response.redirect(env.PRIMARY_ORIGIN + url.pathname + url.search, 308);
  }
};
