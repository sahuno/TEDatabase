/**
 * browser.js — L1-Somatic-DB
 * Author: Samuel Ahuno
 * Date: 2026-04-20
 * Purpose: JBrowse2 genome browser initialization for browser.html
 *
 * Expects the following globals loaded via CDN before this script:
 *   window.React, window.ReactDOM (react 18 UMD)
 *   window.JBrowseReactLinearGenomeView  (JBrowse2 UMD)
 */

(function () {
  'use strict';

  /* ── Configuration ─────────────────────────────────────────────────── */

  const DEFAULT_LOCATION = 'chr2:131,000,000-132,000,000';

  /**
   * JBrowse2 assembly definition for hg38.
   * Uses UCSC chromSizes for sequence names/lengths (no sequence fetching needed
   * for a feature-only view). The adapter type "ChromSizesAdapter" is available
   * in the JBrowse2 UMD build and works client-side without a server.
   */
  const HG38_ASSEMBLY = {
    name: 'hg38',
    sequence: {
      type: 'ReferenceSequenceTrack',
      trackId: 'hg38-reference-sequence',
      adapter: {
        type: 'ChromSizesAdapter',
        chromSizesLocation: {
          uri: 'https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.chrom.sizes',
          locationType: 'UriLocation'
        }
      }
    },
    aliases: ['GRCh38'],
    refNameAliases: {
      adapter: {
        type: 'RefNameAliasAdapter',
        location: {
          uri: 'https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.chrom.sizes',
          locationType: 'UriLocation'
        }
      }
    }
  };

  /**
   * Track definitions.
   */
  const TRACKS = [
    // 1. RefSeq genes (BigBed)
    {
      type:       'FeatureTrack',
      trackId:    'refseq-genes',
      name:       'RefSeq Genes',
      assemblyNames: ['hg38'],
      category:   ['Genes'],
      adapter: {
        type: 'BigBedAdapter',
        bigBedLocation: {
          uri: 'https://hgdownload.soe.ucsc.edu/gbdb/hg38/ncbiRefSeq/ncbiRefSeq.bb',
          locationType: 'UriLocation'
        }
      },
      displays: [{
        type: 'LinearBasicDisplay',
        displayId: 'refseq-genes-display'
      }]
    },

    // 2. L1-Somatic-DB loci (local BED)
    {
      type:       'FeatureTrack',
      trackId:    'l1-somatic-loci',
      name:       'L1-Somatic-DB Loci',
      assemblyNames: ['hg38'],
      category:   ['L1-Somatic-DB'],
      adapter: {
        type: 'BedTabixAdapter',
        bedGzLocation: {
          uri: 'data/loci_hg38.bed.gz',
          locationType: 'UriLocation'
        },
        index: {
          location: {
            uri: 'data/loci_hg38.bed.gz.tbi',
            locationType: 'UriLocation'
          }
        }
      },
      displays: [{
        type: 'LinearBasicDisplay',
        displayId: 'l1-somatic-loci-display',
        renderer: {
          type:       'SvgFeatureRenderer',
          color1:     '#1a5fa8',
          height:     12,
          displayMode: 'normal'
        }
      }]
    },

    // 3. RepeatMasker LINE (BigBed)
    {
      type:       'FeatureTrack',
      trackId:    'repeatmasker-line',
      name:       'RepeatMasker LINE',
      assemblyNames: ['hg38'],
      category:   ['Repeats'],
      adapter: {
        type: 'BigBedAdapter',
        bigBedLocation: {
          uri: 'https://hgdownload.soe.ucsc.edu/gbdb/hg38/bbi/rmsk/rmsk_LINE.bb',
          locationType: 'UriLocation'
        }
      },
      displays: [{
        type: 'LinearBasicDisplay',
        displayId: 'repeatmasker-line-display'
      }]
    }
  ];

  /* ── URL Hash Parsing ──────────────────────────────────────────────── */

  /**
   * Parse a location string from the URL hash.
   * Accepts "#chrN:start-end" format (with optional commas in numbers).
   * Returns the location string for JBrowse2 or null if no valid hash.
   * @returns {string|null}
   */
  function parseHashLocation() {
    const hash = window.location.hash.replace(/^#/, '').trim();
    if (!hash) return null;

    // Pattern: chrN:digits-digits (commas and spaces allowed in numbers)
    const match = hash.match(/^(chr[\w]+):(\d[\d,]*)-(\d[\d,]*)$/i);
    if (!match) return null;

    const chrom = match[1];
    const start = parseInt(match[2].replace(/,/g, ''), 10);
    const end   = parseInt(match[3].replace(/,/g, ''), 10);
    if (isNaN(start) || isNaN(end) || start >= end) return null;

    return `${chrom}:${start}-${end}`;
  }

  /* ── Browser Initialization ────────────────────────────────────────── */

  /**
   * Show a message in the browser container instead of the JBrowse view.
   * @param {string} msg
   * @param {boolean} isError
   */
  function showContainerMessage(msg, isError) {
    const container = document.getElementById('browser-container');
    if (!container) return;
    container.innerHTML = `
      <div class="browser-placeholder${isError ? ' error' : ''}">
        <span>${isError ? 'Error: ' : ''}${msg}</span>
        ${isError ? '<small>Check the browser console for details.</small>' : ''}
      </div>`;
  }

  /**
   * Initialize JBrowse2 using the UMD react-linear-genome-view build.
   * The UMD bundle exposes: window.JBrowseReactLinearGenomeView
   * which contains { createViewState, JBrowseLGV } plus React rendering helpers.
   */
  function initBrowser() {
    const container = document.getElementById('browser-container');
    if (!container) {
      console.error('browser.js: #browser-container element not found');
      return;
    }

    // Verify required globals
    if (typeof window.JBrowseReactLinearGenomeView === 'undefined') {
      showContainerMessage('JBrowse2 library failed to load. Check your internet connection.', true);
      console.error('browser.js: JBrowseReactLinearGenomeView is not defined');
      return;
    }
    if (typeof window.React === 'undefined' || typeof window.ReactDOM === 'undefined') {
      showContainerMessage('React failed to load. Check your internet connection.', true);
      return;
    }

    const { createViewState, JBrowseLGV } = window.JBrowseReactLinearGenomeView;

    if (typeof createViewState !== 'function' || typeof JBrowseLGV === 'undefined') {
      showContainerMessage('JBrowse2 API not available in this build.', true);
      console.error('browser.js: createViewState or JBrowseLGV missing from UMD bundle');
      return;
    }

    // Determine initial location from hash or default.
    const hashLoc = parseHashLocation();
    const initialLocation = hashLoc || DEFAULT_LOCATION;

    let state;
    try {
      state = createViewState({
        assembly:    HG38_ASSEMBLY,
        tracks:      TRACKS,
        location:    initialLocation,
        defaultSession: {
          name:  'L1-Somatic-DB Session',
          views: [{
            id:            'lgv-view',
            type:          'LinearGenomeView',
            bpPerPx:       1,
            tracks:        TRACKS.map(t => ({ id: t.trackId, type: t.type })),
            displayedRegions: []
          }]
        }
      });
    } catch (err) {
      showContainerMessage('Failed to create JBrowse2 view state: ' + err.message, true);
      console.error('browser.js: createViewState error:', err);
      return;
    }

    // Clear placeholder content and render JBrowse2.
    container.innerHTML = '';

    try {
      const React     = window.React;
      const ReactDOM  = window.ReactDOM;
      const element   = React.createElement(JBrowseLGV, { viewState: state });
      ReactDOM.render(element, container);
    } catch (err) {
      showContainerMessage('Failed to render JBrowse2: ' + err.message, true);
      console.error('browser.js: ReactDOM.render error:', err);
      return;
    }

    /* ── Hash Change Navigation ──────────────────────────────────────── */

    /**
     * Navigate the JBrowse2 view to the region encoded in the current URL hash.
     */
    function navigateFromHash() {
      const loc = parseHashLocation();
      if (!loc) return;
      try {
        // Access the first LinearGenomeView in the session.
        const view = state.session.views[0];
        if (view && typeof view.navToLocString === 'function') {
          view.navToLocString(loc);
        }
      } catch (err) {
        console.warn('browser.js: hash navigation failed:', err);
      }
    }

    window.addEventListener('hashchange', navigateFromHash);
  }

  /* ── Entry Point ───────────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', function () {
    // Show loading state while JBrowse2 scripts finish loading.
    // Scripts in browser.html are loaded with defer, so by DOMContentLoaded
    // they should be available. If not, we retry once after a short delay.
    if (typeof window.JBrowseReactLinearGenomeView !== 'undefined') {
      initBrowser();
    } else {
      // Wait for UMD scripts to finish (they may load asynchronously).
      let attempts = 0;
      const maxAttempts = 20;
      const interval = setInterval(function () {
        attempts++;
        if (typeof window.JBrowseReactLinearGenomeView !== 'undefined') {
          clearInterval(interval);
          initBrowser();
        } else if (attempts >= maxAttempts) {
          clearInterval(interval);
          showContainerMessage(
            'JBrowse2 library did not load within the expected time. Check your internet connection.',
            true
          );
        }
      }, 500);
    }
  });

})();
