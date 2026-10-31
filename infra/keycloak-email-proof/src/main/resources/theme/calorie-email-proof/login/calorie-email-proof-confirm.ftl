<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=true; section>
  <#if section == "header">${msg("calorieEmailProofTitle")}
  <#elseif section == "form">
    <p>${msg("calorieEmailProofConfirmHelp")}</p>
    <form id="calorie-email-proof-confirm" action="${url.loginAction}" method="post">
      <input type="hidden" name="email_proof" value="${emailProofToken}">
      <button type="submit">${msg("calorieEmailProofConfirm")}</button>
    </form>
  </#if>
</@layout.registrationLayout>
