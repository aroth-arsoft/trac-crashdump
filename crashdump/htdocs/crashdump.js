
(function($){

  $.fn.crashdump_delayLoadFolding = function(autofold, snap, click_func) {
    var fragId = document.location.hash;
    if (fragId && /^#dno\d+$/.test(fragId))
      fragId = parseInt(fragId.substr(3));
    if (snap == undefined)
      snap = false;

    var count = 1;
    return this.each(function() {
      // Use first child <a> as a trigger, or generate a trigger from the text
      var trigger = $(this).children("a").eq(0);
      if (trigger.length == 0) {
        trigger = $("<a" + (snap? " class='delay_folding' id='dno" + count + "'": "")
            + " href='#dno" + count + "'></a>");
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
