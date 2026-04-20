/**
 * table.js — L1-Somatic-DB
 * Author: Samuel Ahuno
 * Date: 2026-04-20
 * Purpose: DataTables initialization, filter logic, and stats banner for index.html
 */

(function () {
  'use strict';

  /* ── Helpers ───────────────────────────────────────────────────────── */

  /**
   * Escape HTML special characters to prevent XSS.
   * @param {string} str
   * @returns {string}
   */
  function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /**
   * Coerce an array-or-scalar field to an array.
   * @param {*} val
   * @returns {Array}
   */
  function toArray(val) {
    if (!val) return [];
    return Array.isArray(val) ? val : [val];
  }

  /**
   * Format a locus position cell as a link to browser.html with ±5000 bp padding.
   * @param {Object} row
   * @returns {string} HTML
   */
  function formatPosition(row) {
    const chrom = escHtml(row.chrom || '');
    const start = parseInt(row.start, 10);
    const end   = parseInt(row.end,   10);
    if (!chrom || isNaN(start) || isNaN(end)) return escHtml(row.locus_id || '—');

    const padStart = Math.max(0, start - 5000);
    const padEnd   = end + 5000;
    const label    = `${chrom}:${start.toLocaleString()}-${end.toLocaleString()}`;
    const href     = `browser.html#${chrom}:${padStart}-${padEnd}`;

    return `<a class="pos-link" href="${href}" title="Open in genome browser">${escHtml(label)}</a>`;
  }

  /**
   * Format validation level as a colored badge.
   * @param {string} level
   * @returns {string} HTML
   */
  function formatBadge(level) {
    const cls = {
      experimental: 'badge-experimental',
      computational: 'badge-computational',
      predicted: 'badge-predicted'
    }[level] || 'badge-predicted';
    return `<span class="badge ${cls}">${escHtml(level || 'unknown')}</span>`;
  }

  /**
   * Format coordinate confidence as a colored dot + label.
   * @param {string} conf
   * @returns {string} HTML
   */
  function formatConfidence(conf) {
    const cls = {
      high:   'conf-high',
      medium: 'conf-medium',
      low:    'conf-low'
    }[conf] || 'conf-low';
    return `<span class="conf-dot ${cls}">${escHtml(conf || '—')}</span>`;
  }

  /**
   * Format source_pmid field as comma-separated PubMed links.
   * @param {string|string[]} pmids
   * @returns {string} HTML
   */
  function formatPmids(pmids) {
    const arr = toArray(pmids).filter(Boolean);
    if (!arr.length) return '—';
    return arr.map(pmid => {
      const clean = String(pmid).trim();
      return `<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(clean)}/"
                 target="_blank"
                 rel="noopener noreferrer">${escHtml(clean)}</a>`;
    }).join(', ');
  }

  /**
   * Format gene name + region.
   * @param {Object} row
   * @returns {string}
   */
  function formatGene(row) {
    const name   = escHtml(row.gene_name   || '—');
    const region = escHtml(row.gene_region || '');
    return region ? `${name} <span style="color:#777;font-size:0.8em">(${region})</span>` : name;
  }

  /**
   * Format L1 family + subtype.
   * @param {Object} row
   * @returns {string}
   */
  function formatFamily(row) {
    const family  = escHtml(row.l1_family  || '—');
    const subtype = escHtml(row.l1_subtype || '');
    return subtype ? `${family} <span style="color:#777;font-size:0.8em">${subtype}</span>` : family;
  }

  /**
   * Format tissue + cancer types.
   * @param {Object} row
   * @returns {string}
   */
  function formatTissue(row) {
    const tissues = toArray(row.tissue_type).join(', ') || '—';
    const cancers = toArray(row.cancer_type).join(', ');
    const base    = escHtml(tissues);
    return cancers
      ? `${base} <span style="color:#777;font-size:0.8em">(${escHtml(cancers)})</span>`
      : base;
  }

  /* ── Stats Banner ──────────────────────────────────────────────────── */

  /**
   * Populate the 4-card stats banner from stats.json.
   * @param {Object} stats
   */
  function populateStats(stats) {
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val !== undefined && val !== null ? val : '—';
    };
    set('stat-total',     (stats.total_loci     || 0).toLocaleString());
    set('stat-validated', (stats.validated_loci  || 0).toLocaleString());
    set('stat-papers',    (stats.papers_processed || 0).toLocaleString());
    set('stat-updated',   stats.last_updated || '—');
  }

  /* ── DataTables Filter Extension ──────────────────────────────────── */

  // Storage for current filter values — read by the custom search function.
  const activeFilters = {
    chrom:      '',
    validation: '',
    sourceType: '',
    yearFrom:   '',
    yearTo:     ''
  };

  /**
   * Register a single custom search function that checks all dropdowns + year range.
   * Called once during setup — DataTables re-evaluates it on every draw.
   */
  function registerCustomFilters() {
    $.fn.dataTable.ext.search.push(function (_settings, _data, _idx, rowData) {
      // rowData is the raw locus object stored as the DataTables row data.

      // Chromosome filter
      if (activeFilters.chrom && rowData.chrom !== activeFilters.chrom) return false;

      // Validation level filter
      if (activeFilters.validation && rowData.validation_level !== activeFilters.validation) return false;

      // Source type filter
      if (activeFilters.sourceType && rowData.source_type !== activeFilters.sourceType) return false;

      // Year range filter
      const year = parseInt(rowData.paper_year, 10);
      if (activeFilters.yearFrom && !isNaN(year) && year < parseInt(activeFilters.yearFrom, 10)) return false;
      if (activeFilters.yearTo   && !isNaN(year) && year > parseInt(activeFilters.yearTo,   10)) return false;

      return true;
    });
  }

  /* ── Chromosome Dropdown ───────────────────────────────────────────── */

  /**
   * Natural-sort chromosome list: numeric first, then X, Y, M, unknowns.
   * @param {string[]} chroms
   * @returns {string[]}
   */
  function sortChroms(chroms) {
    return chroms.slice().sort((a, b) => {
      const numA = parseInt(a.replace('chr', ''), 10);
      const numB = parseInt(b.replace('chr', ''), 10);
      const aIsNum = !isNaN(numA);
      const bIsNum = !isNaN(numB);
      if (aIsNum && bIsNum)  return numA - numB;
      if (aIsNum && !bIsNum) return -1;
      if (!aIsNum && bIsNum) return 1;
      return a.localeCompare(b);
    });
  }

  /**
   * Populate chromosome select from data.
   * @param {Object[]} loci
   */
  function populateChromDropdown(loci) {
    const select = document.getElementById('filter-chrom');
    if (!select) return;
    const unique = [...new Set(loci.map(d => d.chrom).filter(Boolean))];
    const sorted = sortChroms(unique);
    sorted.forEach(chrom => {
      const opt = document.createElement('option');
      opt.value = chrom;
      opt.textContent = chrom;
      select.appendChild(opt);
    });
  }

  /**
   * Set min/max on year range inputs from data.
   * @param {Object[]} loci
   */
  function populateYearRange(loci) {
    const years = loci.map(d => parseInt(d.paper_year, 10)).filter(y => !isNaN(y));
    if (!years.length) return;
    const minYear = Math.min(...years);
    const maxYear = Math.max(...years);
    const fromEl = document.getElementById('filter-year-from');
    const toEl   = document.getElementById('filter-year-to');
    if (fromEl) { fromEl.min = minYear; fromEl.max = maxYear; fromEl.placeholder = minYear; }
    if (toEl)   { toEl.min   = minYear; toEl.max   = maxYear; toEl.placeholder   = maxYear; }
  }

  /* ── DataTables Initialization ─────────────────────────────────────── */

  /**
   * Build a plain-text searchable string from a row for DataTables global search.
   * @param {Object} row
   * @returns {string}
   */
  function rowToSearchText(row) {
    const fields = [
      row.locus_id, row.chrom,
      row.gene_name, row.gene_region,
      row.l1_family, row.l1_subtype, row.insertion_type,
      row.validation_level, row.source_type, row.coordinate_confidence,
      row.paper_year, row.paper_journal, row.paper_title, row.notes,
      toArray(row.tissue_type).join(' '),
      toArray(row.cancer_type).join(' '),
      toArray(row.validation_method).join(' '),
      toArray(row.detection_method).join(' '),
      toArray(row.source_pmid).join(' ')
    ];
    return fields.filter(Boolean).join(' ').toLowerCase();
  }

  /**
   * Initialize DataTables with loci data.
   * @param {Object[]} loci
   */
  function initDataTable(loci) {
    const tableEl = document.getElementById('loci-table');
    if (!tableEl) return;

    // Build row data arrays — DataTables works with arrays of values per row.
    // We also attach the raw object as row data for custom filtering.
    const tableData = loci.map(row => ({
      // Rendered columns (HTML strings)
      position:   formatPosition(row),
      gene:       formatGene(row),
      family:     formatFamily(row),
      tissue:     formatTissue(row),
      validation: formatBadge(row.validation_level),
      evidence:   escHtml(toArray(row.detection_method).join(', ') || '—'),
      samples:    row.n_samples_detected !== null && row.n_samples_detected !== undefined
                    ? escHtml(String(row.n_samples_detected))
                    : '—',
      year:       escHtml(String(row.paper_year || '—')),
      pmid:       formatPmids(row.source_pmid),
      confidence: formatConfidence(row.coordinate_confidence),
      // Plain-text for global search
      _search:    rowToSearchText(row),
      // Raw object for custom dropdown/year filters
      _raw:       row
    }));

    // Map to array form expected by DataTables columns
    const arrayData = tableData.map(r => [
      r.position, r.gene, r.family, r.tissue,
      r.validation, r.evidence, r.samples,
      r.year, r.pmid, r.confidence,
      r._search  // hidden column for global search
    ]);

    const dt = $(tableEl).DataTable({
      data: arrayData,
      columns: [
        { title: 'Position',       className: 'col-position' },
        { title: 'Gene',           className: 'col-gene' },
        { title: 'L1 Family',      className: 'col-family' },
        { title: 'Tissue / Cancer',className: 'col-tissue' },
        { title: 'Validation',     className: 'col-validation' },
        { title: 'Evidence',       className: 'col-evidence' },
        { title: 'Samples',        className: 'col-samples', type: 'num' },
        { title: 'Year',           className: 'col-year',    type: 'num' },
        { title: 'PMID',           className: 'col-pmid',    orderable: false },
        { title: 'Confidence',     className: 'col-conf' },
        { title: '_search',        visible: false, searchable: true }
      ],
      // Store raw objects alongside rows for custom filter access.
      // We attach them via rowData after creation.
      order:       [[7, 'desc']],
      pageLength:  25,
      lengthMenu:  [10, 25, 50, 100, 250],
      processing:  true,
      deferRender: true,
      autoWidth:   false,
      dom: '<"top"lf>rt<"bottom"ip>',
      language: {
        search:       'Quick search:',
        lengthMenu:   'Show _MENU_ entries',
        info:         'Showing _START_ to _END_ of _TOTAL_ loci',
        infoEmpty:    'No loci found',
        zeroRecords:  'No matching loci found'
      }
    });

    // Attach raw row objects to each DataTables row for the custom filter.
    // DataTables rows() are in the same order as tableData.
    dt.rows().every(function (rowIdx) {
      this.data()._raw = tableData[rowIdx]._raw;
    });

    // Patch custom search to use raw objects stored in loci array by index.
    // Since we store raw objects in tableData which maps 1:1 to DT rows,
    // we need a different approach: rebuild the custom search to work with column data.
    // Clear the registered search and use a closure approach instead.
    $.fn.dataTable.ext.search.pop(); // Remove the one registered earlier
    $.fn.dataTable.ext.search.push(function (_settings, data, rowIndex) {
      const raw = tableData[rowIndex]._raw;
      if (!raw) return true;

      if (activeFilters.chrom      && raw.chrom            !== activeFilters.chrom)      return false;
      if (activeFilters.validation && raw.validation_level !== activeFilters.validation) return false;
      if (activeFilters.sourceType && raw.source_type      !== activeFilters.sourceType) return false;

      const year = parseInt(raw.paper_year, 10);
      if (activeFilters.yearFrom && !isNaN(year) && year < parseInt(activeFilters.yearFrom, 10)) return false;
      if (activeFilters.yearTo   && !isNaN(year) && year > parseInt(activeFilters.yearTo,   10)) return false;

      return true;
    });

    return dt;
  }

  /* ── Filter Event Binding ──────────────────────────────────────────── */

  /**
   * Wire up all filter controls to update activeFilters and redraw.
   * @param {Object} dt — DataTables instance
   */
  function bindFilters(dt) {
    // Text search (uses DataTables built-in)
    const searchInput = document.getElementById('filter-search');
    if (searchInput) {
      searchInput.addEventListener('input', function () {
        dt.search(this.value).draw();
      });
    }

    // Chromosome dropdown
    const chromSel = document.getElementById('filter-chrom');
    if (chromSel) {
      chromSel.addEventListener('change', function () {
        activeFilters.chrom = this.value;
        dt.draw();
      });
    }

    // Validation level dropdown
    const validSel = document.getElementById('filter-validation');
    if (validSel) {
      validSel.addEventListener('change', function () {
        activeFilters.validation = this.value;
        dt.draw();
      });
    }

    // Source type dropdown
    const srcSel = document.getElementById('filter-source');
    if (srcSel) {
      srcSel.addEventListener('change', function () {
        activeFilters.sourceType = this.value;
        dt.draw();
      });
    }

    // Year range inputs
    const yearFrom = document.getElementById('filter-year-from');
    const yearTo   = document.getElementById('filter-year-to');
    if (yearFrom) {
      yearFrom.addEventListener('input', function () {
        activeFilters.yearFrom = this.value.trim();
        dt.draw();
      });
    }
    if (yearTo) {
      yearTo.addEventListener('input', function () {
        activeFilters.yearTo = this.value.trim();
        dt.draw();
      });
    }

    // Reset button
    const resetBtn = document.getElementById('btn-reset');
    if (resetBtn) {
      resetBtn.addEventListener('click', function () {
        // Clear DOM controls
        if (searchInput) searchInput.value = '';
        if (chromSel)    chromSel.value    = '';
        if (validSel)    validSel.value    = '';
        if (srcSel)      srcSel.value      = '';
        if (yearFrom)    yearFrom.value    = '';
        if (yearTo)      yearTo.value      = '';

        // Clear internal state
        Object.keys(activeFilters).forEach(k => { activeFilters[k] = ''; });

        // Reset DataTables search and redraw
        dt.search('').draw();
      });
    }
  }

  /* ── Entry Point ───────────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', function () {
    const statusEl = document.getElementById('table-status');

    function showStatus(msg, isError) {
      if (!statusEl) return;
      statusEl.textContent = msg;
      statusEl.className   = 'status-message' + (isError ? ' error' : '');
    }

    showStatus('Loading data…');

    // Register the placeholder custom search function early (will be replaced after data loads).
    registerCustomFilters();

    // Fetch both JSON files in parallel.
    Promise.all([
      fetch('data/loci.json').then(r => {
        if (!r.ok) throw new Error(`loci.json: HTTP ${r.status}`);
        return r.json();
      }),
      fetch('data/stats.json').then(r => {
        if (!r.ok) throw new Error(`stats.json: HTTP ${r.status}`);
        return r.json();
      })
    ]).then(([loci, stats]) => {
      // Stats banner
      populateStats(stats);

      // Populate dynamic filter options
      populateChromDropdown(loci);
      populateYearRange(loci);

      // Hide status, show table wrapper
      if (statusEl) statusEl.style.display = 'none';
      const tableWrapper = document.getElementById('table-wrapper');
      if (tableWrapper) tableWrapper.style.display = '';

      // Boot DataTables
      const dt = initDataTable(loci);
      if (dt) bindFilters(dt);

    }).catch(err => {
      console.error('Failed to load data:', err);
      showStatus('Error loading data: ' + err.message, true);
    });
  });

})();
