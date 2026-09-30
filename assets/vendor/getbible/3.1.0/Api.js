import {Memory} from './Memory.js';

/**
 * Class for handling API calls to fetch scripture data.
 */
export class Api {
  /**
   * Constructs an Api instance with a default or specified API endpoint.
   *
   * @param {string} apiEndpoint - The endpoint URL for the API.
   */
  constructor(apiEndpoint = 'https://query.getbible.net/v2/', { fetchImpl = globalThis.fetch, timeoutMs = 12000 } = {}) {
    this.apiEndpoint = apiEndpoint;
    this.fetchImpl = fetchImpl;
    this.timeoutMs = timeoutMs;
  }

  /**
   * Fetches scripture from the API, using local storage to cache responses.
   *
   * @param {string} reference - The scripture reference.
   * @param {string} translation - The translation.
   * @returns {Promise<Object>} A promise that resolves with the scripture data.
   * @throws {Error} If the API request fails.
   */
  async get(reference, translation) {
    try {
      const localStorageData = await Memory.get(reference, translation);
      if (localStorageData !== null) {
        return localStorageData;
      }

      // Remnant adapter: bound connection and body reads; tests inject fetch.
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let data;
      try {
        const response = await this.fetchImpl(this.#url(reference, translation), {
          signal: controller.signal, credentials: 'omit', referrerPolicy: 'no-referrer'
        });
        if (!response.ok) {
          throw new Error(`${response.status} - ${response.statusText || 'Failed to fetch scripture'}`);
        }
        data = await response.json();
      } finally {
        clearTimeout(timer);
      }
      await Memory.set(reference, translation, data);
      return data;
    } catch (error) {
      console.error('Error fetching data:', error);
      throw new Error(error.message || 'Error fetching scripture');
    }
  }

  /**
   * Constructs the URL for the API call.
   *
   * @param {string} reference - The scripture reference.
   * @param {string} translation - The translation.
   * @returns {string} The constructed URL for the API request.
   * @private
   */
  #url(reference, translation) {
    return `${this.apiEndpoint}${encodeURIComponent(translation)}/${encodeURIComponent(reference)}`;
  }
}
