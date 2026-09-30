/**
 * Class for handling chapter data.
 */
export class Reference {
  #data; // Private data member

  /**
   * Initializes the BibleVerse object with verse data.
   *
   * @param {Object} data - The JSON data containing verse information.
   * @param {string} data.translation - The name of the translation.
   * @param {string} data.abbreviation - The abbreviation of the translation.
   * @param {string} data.language - The full language name.
   * @param {string} data.lang - The language code.
   * @param {string} data.direction - The text direction (LTR or RTL).
   * @param {string} data.encoding - The encoding format (e.g., UTF-8).
   * @param {number} data.book_nr - The book number.
   * @param {string} data.book_name - The name of the book.
   * @param {number} data.chapter - The chapter number.
   * @param {string} data.name - The name of the chapter.
   * @param {Array<Object>} data.verses - An array of objects representing each verse.
   * @param {string|Array<string>} data.ref - The local reference string or array of strings.
   */
  constructor(data) {
    // Simple validation to check if essential properties are present
    const requiredProperties = [
      'translation', 'abbreviation', 'language', 'lang',
      'direction', 'encoding', 'book_nr', 'book_name',
      'chapter', 'name', 'verses', 'ref'
    ];

    if (!data || typeof data !== 'object') {
      throw new Error('Data must be a valid object.');
    }

    requiredProperties.forEach(prop => {
      if (data[prop] === undefined || data[prop] === null) {
        throw new Error(`Missing required property: '${prop}'.`);
      }
    });

    // Assign the data after validation
    this.#data = data;
  }

  /**
   * Retrieves the url values.
   *
   * @returns {string} The chapter number.
   */
  get bibleUrl() {
    return `${this.abbreviation}/${this.bookName}/${this.chapter}/${this.verseReference}`;
  }

  /**
   * Retrieves the translation name.
   *
   * @returns {string} The name of the translation.
   */
  get translation() {
    return this.#data.translation;
  }

  /**
   * Retrieves the abbreviation of the translation.
   *
   * @returns {string} The abbreviation of the translation.
   */
  get abbreviation() {
    return this.#data.abbreviation;
  }

  /**
   * Retrieves the full language name.
   *
   * @returns {string} The language code.
   */
  get language() {
    return this.#data.language;
  }

  /**
   * Retrieves the language code.
   *
   * @returns {string} The full name of the language.
   */
  get languageCode() {
    return this.#data.lang;
  }

  /**
   * Retrieves the text direction.
   *
   * @returns {string} The direction of the text (LTR or RTL).
   */
  get textDirection() {
    return this.#data.direction;
  }

  /**
   * Retrieves the encoding format.
   *
   * @returns {string} The encoding format (e.g., UTF-8).
   */
  get encoding() {
    return this.#data.encoding;
  }

  /**
   * Retrieves the book number.
   *
   * @returns {number} The book number.
   */
  get bookNumber() {
    return this.#data.book_nr;
  }

  /**
   * Retrieves the name of the book.
   *
   * @returns {string} The name of the book.
   */
  get bookName() {
    return this.#data.book_name;
  }

  /**
   * Retrieves the chapter number.
   *
   * @returns {number} The chapter number.
   */
  get chapter() {
    return this.#data.chapter;
  }

  /**
   * Retrieves the name of the chapter.
   *
   * @returns {string} The name of the chapter.
   */
  get chapterName() {
    return this.#data.name;
  }

  /**
   * Retrieves all verses of the chapter.
   *
   * @returns {Array<{chapter: number, verse: number, name: string, text: string}>}
   *          An array of objects representing each verse.
   */
  get verses() {
    return this.#data.verses;
  }

  /**
   * Retrieves a specific verse by its number.
   *
   * @param {number} verseNumber - The number of the verse to retrieve.
   * @returns {Object|null} The verse object if found, or null if not.
   */
  getVerse(verseNumber) {
    return this.#data.verses.find(verse => verse.verse === verseNumber);
  }

  /**
   * Retrieves a range of verses.
   *
   * @param {number} startVerse - The starting verse number.
   * @param {number} endVerse - The ending verse number.
   * @returns {Array<Object>} An array of verse objects within the range.
   */
  getVersesInRange(startVerse, endVerse) {
    return this.#data.verses.filter(verse => verse.verse >= startVerse && verse.verse <= endVerse);
  }

  /**
   * Get the local reference string set in the website.
   *
   * @returns {string} The reference string.
   */
  get localReference() {
    // Ensure that this.#data.ref is treated as an array.
    return Array.isArray(this.#data.ref) ? this.#data.ref.join('; ') : this.#data.ref;
  }

  /**
   * Generates a reference string for the (book chapter:verses).
   *
   * @returns {string} The reference string.
   */
  get reference() {
    return `${this.#data.name}:${this.verseReference}`;
  }

  /**
   * Generates a reference string for the (verses).
   *
   * @returns {string} The reference verses string.
   */
  get verseReference() {
    const verseNumbers = this.#data.verses.map(verse => verse.verse).sort((a, b) => a - b);
    let ranges = {};
    let rangeStart = null;
    let rangeEnd = null;
    let previousVerse = null;

    verseNumbers.forEach(verse => {
      if (rangeStart === null) {
        rangeStart = verse;
      } else if (verse === previousVerse + 1) {
        rangeEnd = verse;
      } else {
        ranges[rangeStart] = (rangeEnd !== null) ? `${rangeStart}-${rangeEnd}` : `${rangeStart}`;
        rangeStart = verse;
        rangeEnd = null;
      }
      previousVerse = verse;
    });

    // Handling the case for the last verse or a single-verse range
    if (rangeStart !== null) {
      ranges[rangeStart] = (rangeEnd !== null) ? `${rangeStart}-${rangeEnd}` : `${rangeStart}`;
    }

    // Join the range strings with commas
    return Object.values(ranges).join(',');
  }
}
