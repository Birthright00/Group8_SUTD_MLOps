/**
 * API Configuration
 *
 * Switch between local development and Modal production deployment.
 */

const API_CONFIG = {
  // Modal endpoints (from .env)
  MODAL_ANALYZE_URL: import.meta.env.VITE_MODAL_ANALYZE_URL,
  MODAL_CHAT_URL: import.meta.env.VITE_MODAL_CHAT_URL,
  MODAL_EDIT_IMAGE_URL: import.meta.env.VITE_MODAL_EDIT_IMAGE_URL,
  MODAL_COMPLETE_PIPELINE_URL: import.meta.env.VITE_MODAL_ANALYZE_URL,

  // Local endpoints (Vite proxy handles routing)
  LOCAL_ANALYZE_URL: '/api/analyze',
  LOCAL_CHAT_URL: '/api/chat',

  // Use Modal or local proxy (from .env)
  USE_MODAL: import.meta.env.VITE_USE_MODAL === 'true',
};

/**
 * Get the analyze endpoint URL
 * @returns {string} API endpoint URL
 */
export function getAnalyzeUrl() {
  const url = API_CONFIG.USE_MODAL
    ? API_CONFIG.MODAL_ANALYZE_URL
    : API_CONFIG.LOCAL_ANALYZE_URL;

  console.log(`[API] Using ${API_CONFIG.USE_MODAL ? 'Modal' : 'Local'} analyze endpoint:`, url);
  return url;
}

/**
 * Get the chat endpoint URL
 * @returns {string} API endpoint URL
 */
export function getChatUrl() {
  const url = API_CONFIG.USE_MODAL
    ? API_CONFIG.MODAL_CHAT_URL
    : API_CONFIG.LOCAL_CHAT_URL;

  console.log(`[API] Using ${API_CONFIG.USE_MODAL ? 'Modal' : 'Local'} chat endpoint:`, url);
  return url;
}

/**
 * Get the edit image endpoint URL
 * @returns {string} API endpoint URL
 */
export function getEditImageUrl() {
  const url = API_CONFIG.USE_MODAL
    ? API_CONFIG.MODAL_EDIT_IMAGE_URL
    : API_CONFIG.LOCAL_ANALYZE_URL; // fallback to local

  console.log(`[API] Using ${API_CONFIG.USE_MODAL ? 'Modal' : 'Local'} edit image endpoint:`, url);
  return url;
}

/**
 * Get the complete pipeline endpoint URL
 * @returns {string} API endpoint URL
 */
export function getCompletePipelineUrl() {
  const url = API_CONFIG.USE_MODAL
    ? API_CONFIG.MODAL_COMPLETE_PIPELINE_URL
    : API_CONFIG.LOCAL_ANALYZE_URL; // fallback to local

  console.log(`[API] Using ${API_CONFIG.USE_MODAL ? 'Modal' : 'Local'} complete pipeline endpoint:`, url);
  return url;
}

/**
 * Check if using Modal endpoints
 * @returns {boolean}
 */
export function isUsingModal() {
  return API_CONFIG.USE_MODAL;
}

export default API_CONFIG;
