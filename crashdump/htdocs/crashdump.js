function crashdump_clickFolding(node, expanded) {
    if (expanded == true) {
        var url = window.location.href;
        var path = window.location.pathname;
        var target_url = (path + '/').replace('//', '/') + node.id.replace(/___/g, '/');

        $( '#' + node.id).children('div#placeholder').html('<div class="loading_message">Loading...</div>');
        //$( '#' + node.id).children('div#placeholder').html('here ' + node.id + ' exp=' + expanded + ' url=' + url + ' path=' + path);
        $( '#' + node.id).children('div#placeholder').load(target_url, {}, enableDelayLoadFolding);

        console.log('here node.id=' + node.id + ' exp=' + expanded + ' url=' + target_url);
    } else {
        //console.log('nno ' + node.id + ' exp=' + expanded);
        //$( '#' + node.id).children('div#placeholder').text('');
    }
}
function enableDelayLoadFolding(node, status) {
    console.log('Loaded ' + this.parentNode.id);
    $(this).children("div").children(".delayfoldable").crashdump_delayLoadFolding(false, true, crashdump_clickFolding, this.parentNode.id);
}
function crashdump_docReady() {
    jQuery(document).ready(function($) {
    // activate the trac folding
    $(".foldable").enableFolding(false, true)
    // activate our delay folding
    $(".delayfoldable").crashdump_delayLoadFolding(false, true, crashdump_clickFolding);
    });
}
(function($){

  $.fn.crashdump_delayLoadFolding = function(autofold, snap, click_func, prefix=null) {
    var fragId = document.location.hash;
    var linkid = 'dno' + (prefix != null?prefix:'');
    var regex = new RegExp('^#' + linkid + '\d+$');
    if (fragId && regex.test(fragId))
      fragId = parseInt(fragId.substr(3));
    if (snap == undefined)
      snap = false;

    var count = 1;
    return this.each(function() {
      // Use first child <a> as a trigger, or generate a trigger from the text
      var trigger = $(this).children("a").eq(0);
      if (trigger.length == 0) {
        trigger = $("<a" + (snap? " class='delay_folding' id='" + linkid + count + "'": "")
            + " href='#" + linkid + count + "'></a>");
        trigger.html($(this).html());
        $(this).text("");
        $(this).append(trigger);
        $(this.parentNode).append("<div id='placeholder'></div>");
        var expanded = snap && !$(this.parentNode).hasClass("collapsed");
        click_func(this.parentNode, expanded);
      }

      trigger.click(function() {
        var div = $(this.parentNode.parentNode).toggleClass("collapsed");
        var expanded = snap && !div.hasClass("collapsed");
        click_func(this.parentNode.parentNode, expanded);
        return expanded;
      });
      if (autofold && (count != fragId))
        trigger.parents().eq(1).addClass("collapsed");
      count++;
    });
  }
})(jQuery);
